"""P3.9 Isolation boundary tests.

Tests are environment-gated: real Win32 isolation tests run on Windows,
contract tests run everywhere.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

from packages.platform.windows.isolation import (
    DEFAULT_ENV_WHITELIST,
    SECRET_ENV_BLOCKLIST,
    IsolationBoundary,
    IsolationConfig,
    SecretHandle,
    WindowsIsolationBroker,
    create_default_isolation,
)


class TestEnvironmentFiltering:
    """Test environment variable filtering — runs everywhere."""

    def test_whitelist_only_passed(self):
        """Only whitelisted env vars should be in the filtered result."""
        config = IsolationConfig(workspace_root="/tmp")
        broker = WindowsIsolationBroker(config)

        # Set a non-whitelisted var
        os.environ["TEST_SECRET_VAR"] = "should-not-appear"
        try:
            result = broker.filter_environment()
            assert "TEST_SECRET_VAR" not in result
            # Whitelisted vars should be present if they exist in os.environ
            for key in DEFAULT_ENV_WHITELIST:
                if key in os.environ:
                    assert key in result
        finally:
            del os.environ["TEST_SECRET_VAR"]

    def test_secret_env_keys_blocked(self):
        """Env vars with secret-like names must fail closed."""
        config = IsolationConfig(workspace_root="/tmp")
        broker = WindowsIsolationBroker(config)

        for key in (
            "PASSWORD",
            "api_key",
            "Access_Token",
            "DATABASE_URL",
        ):
            with pytest.raises(Exception, match="looks like a secret"):
                broker.filter_environment(extra_env={key: "secret"})

    def test_extra_environment_uses_canonical_windows_key_casing(self):
        """Environment names are case-insensitive and emitted canonically."""
        config = IsolationConfig(
            workspace_root="/tmp",
            env_whitelist=frozenset({"mixed_case_host"}),
        )
        broker = WindowsIsolationBroker(config)

        os.environ["MiXeD_CaSe_HoSt"] = "host-value"
        try:
            result = broker.filter_environment({"normal_var": "extra-value"})
        finally:
            del os.environ["MiXeD_CaSe_HoSt"]

        assert result == {
            "MIXED_CASE_HOST": "host-value",
            "NORMAL_VAR": "extra-value",
        }

    @pytest.mark.parametrize(
        ("key", "value", "message"),
        [
            ("", "value", "invalid environment variable name"),
            ("BAD=KEY", "value", "invalid environment variable name"),
            ("BAD\x00KEY", "value", "invalid environment variable name"),
            ("NORMAL", "bad\x00value", "contains NUL"),
        ],
    )
    def test_invalid_environment_entries_fail_closed(
        self, key: str, value: str, message: str,
    ):
        broker = WindowsIsolationBroker(IsolationConfig(workspace_root="/tmp"))

        with pytest.raises(Exception, match=message):
            broker.filter_environment({key: value})

    def test_non_string_environment_entries_fail_closed(self):
        broker = WindowsIsolationBroker(IsolationConfig(workspace_root="/tmp"))

        with pytest.raises(Exception, match="names must be strings"):
            broker.filter_environment({1: "value"})  # type: ignore[dict-item]
        with pytest.raises(Exception, match="values must be strings"):
            broker.filter_environment({"NORMAL": 1})  # type: ignore[dict-item]

    def test_blocked_count_excludes_allowed_extra_environment(self):
        config = IsolationConfig(
            workspace_root="/tmp",
            env_whitelist=frozenset({"PATH"}),
        )
        broker = WindowsIsolationBroker(config)
        broker._boundary = IsolationBoundary(config=config)
        result = broker.filter_environment({"NORMAL": "value"})

        assert result["NORMAL"] == "value"
        assert broker._boundary.env_vars_blocked == sum(
            1 for key in os.environ if key.upper() != "PATH"
        )

    def test_secret_blocklist_covers_common_patterns(self):
        """Verify blocklist patterns catch common secret names."""
        for name in ["PASSWORD", "API_KEY", "TOKEN", "SECRET", "CREDENTIAL"]:
            assert name in SECRET_ENV_BLOCKLIST or any(
                block in name for block in SECRET_ENV_BLOCKLIST
            )


class TestSecretBroker:
    """Test secret handle lifecycle — runs everywhere."""

    def test_secret_handle_consume_once(self):
        """Secret handle must be consumed exactly once."""
        import time

        handle = SecretHandle(
            handle_id="test-1",
            tool_name="test_tool",
            task_id="task-1",
            created_at=time.time(),
            _value="secret-value",
        )

        # First consume succeeds
        value = handle.consume()
        assert value == "secret-value"

        # Second consume fails
        with pytest.raises(Exception, match="already consumed"):
            handle.consume()

    def test_secret_handle_tool_task_binding(self):
        """Secret handle must verify tool+task binding on consume."""
        config = IsolationConfig(workspace_root="/tmp")
        broker = WindowsIsolationBroker(config)

        broker.issue_secret(
            handle_id="test-2",
            tool_name="tool_a",
            task_id="task_a",
            value="secret123",
        )

        # Correct binding
        value = broker.consume_secret("test-2", "tool_a", "task_a")
        assert value == "secret123"

    def test_secret_handle_wrong_tool_rejected(self):
        """Wrong tool+task binding must be rejected."""
        config = IsolationConfig(workspace_root="/tmp")
        broker = WindowsIsolationBroker(config)

        broker.issue_secret(
            handle_id="test-3",
            tool_name="tool_a",
            task_id="task_a",
            value="secret",
        )

        with pytest.raises(Exception, match="not bound"):
            broker.consume_secret("test-3", "tool_b", "task_a")

    def test_secret_handle_expiry_clears_value(self):
        """Expired handles fail closed and erase the retained value."""

        handle = SecretHandle(
            handle_id="expired",
            tool_name="tool",
            task_id="task",
            created_at=10.0,
            expires_at=11.0,
            _value="sensitive",
        )

        with pytest.raises(Exception, match="expired"):
            handle.consume_at(11.0)

        assert handle.consumed is True
        assert handle._value is None

    def test_secret_handle_duplicate_id_is_rejected(self):
        """A handle ID cannot be silently rebound to a different secret."""

        broker = WindowsIsolationBroker(IsolationConfig(workspace_root="/tmp"))
        first = broker.issue_secret("duplicate", "tool", "task", "first")

        with pytest.raises(Exception, match="already exists"):
            broker.issue_secret("duplicate", "tool", "task", "second")

        assert first.consume() == "first"

    @pytest.mark.parametrize("lifetime_sec", [0, -1, 301])
    def test_secret_handle_invalid_lifetime_is_rejected(self, lifetime_sec: int):
        """TTL must be positive and cannot exceed the configured maximum."""

        broker = WindowsIsolationBroker(
            IsolationConfig(workspace_root="/tmp", max_secret_lifetime_sec=300)
        )

        with pytest.raises(Exception, match="lifetime"):
            broker.issue_secret(
                "ttl",
                "tool",
                "task",
                "value",
                lifetime_sec=lifetime_sec,
            )

    def test_secret_handle_consume_is_atomic_across_threads(self):
        """Concurrent consumers must expose the value to exactly one caller."""

        from concurrent.futures import ThreadPoolExecutor

        handle = SecretHandle(
            handle_id="concurrent",
            tool_name="tool",
            task_id="task",
            created_at=0.0,
            expires_at=float("inf"),
            _value="one-reader-only",
        )

        def consume() -> str:
            try:
                return handle.consume()
            except Exception as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _index: consume(), range(8)))

        assert results.count("one-reader-only") == 1
        assert sum("already consumed" in result for result in results) == 7

    def test_secret_handle_repr_does_not_expose_value(self):
        """Diagnostics must not serialize the in-memory secret value."""

        handle = SecretHandle(
            handle_id="repr",
            tool_name="tool",
            task_id="task",
            created_at=0.0,
            _value="must-not-appear",
        )

        assert "must-not-appear" not in repr(handle)

    def test_broker_close_clears_unconsumed_secret_values(self):
        """Broker shutdown invalidates and erases every outstanding handle."""

        broker = WindowsIsolationBroker(IsolationConfig(workspace_root="/tmp"))
        handle = broker.issue_secret("close", "tool", "task", "sensitive")

        broker.close()

        assert handle.consumed is True
        assert handle._value is None
        assert broker._secret_handles == {}
        with pytest.raises(Exception, match="not available"):
            broker.consume_secret("close", "tool", "task")


class TestEgressControl:
    """Test network egress filtering — runs everywhere."""

    def test_default_deny(self):
        """Egress must be denied by default when no rules match."""
        config = IsolationConfig(
            workspace_root="/tmp",
            enable_egress_filter=True,
        )
        broker = WindowsIsolationBroker(config)

        result = broker.check_egress("evil.com", 443)
        assert result is None

    def test_allowlist_match(self):
        """Egress to allowlisted host:port must be allowed."""
        config = IsolationConfig(
            workspace_root="/tmp",
            egress_allowlist=("api.example.com:443",),
        )
        broker = WindowsIsolationBroker(config)

        result = broker.check_egress("api.example.com", 443)
        assert result is not None
        assert result.host == "api.example.com"
        assert result.port == 443

    def test_wildcard_host_match(self):
        """Wildcard host in allowlist should match any host on that port."""
        config = IsolationConfig(
            workspace_root="/tmp",
            egress_allowlist=("*:80",),
        )
        broker = WindowsIsolationBroker(config)

        result = broker.check_egress("any.host.com", 80)
        assert result is not None

        result_denied = broker.check_egress("any.host.com", 443)
        assert result_denied is None

    def test_egress_filter_disabled_allows_all(self):
        """When egress filter is disabled, all egress is allowed."""
        config = IsolationConfig(
            workspace_root="/tmp",
            enable_egress_filter=False,
        )
        broker = WindowsIsolationBroker(config)

        result = broker.check_egress("anywhere.com", 9999)
        assert result is not None


class TestIsolationInitialization:
    """Test isolation broker initialization — Windows-specific."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_initialize_succeeds_with_valid_workspace(self):
        """A valid workspace must create a verified restricted primary token."""
        import shutil

        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_test_")
        broker = create_default_isolation(workspace)
        try:
            boundary = broker.initialize()
            assert boundary is not None
            assert boundary.initialization_verified
            assert boundary.restricted_token_applied is True
            assert boundary.workspace_acl_applied is True
            assert broker.restricted_token is not None
            assert win32security.IsTokenRestricted(broker.restricted_token)
            assert (
                win32security.GetTokenInformation(
                    broker.restricted_token,
                    win32security.TokenType,
                )
                == 1
            )
        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_restricted_token_disables_admin_sids_and_extra_privileges(self):
        """The runner token must not retain enabled admin groups or privileges."""
        import shutil

        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_token_test_")
        broker = create_default_isolation(workspace)
        try:
            broker.initialize()
            token = broker.restricted_token
            assert token is not None

            privilege_names = {
                win32security.LookupPrivilegeName(None, luid)
                for luid, _attributes in win32security.GetTokenInformation(
                    token,
                    win32security.TokenPrivileges,
                )
            }
            assert privilege_names <= {"SeChangeNotifyPrivilege"}

            groups = {
                win32security.ConvertSidToStringSid(sid): attributes
                for sid, attributes in win32security.GetTokenInformation(
                    token,
                    win32security.TokenGroups,
                )
            }
            for sid_text in ("S-1-5-114", "S-1-5-32-544"):
                if sid_text in groups:
                    assert groups[sid_text] & win32security.SE_GROUP_USE_FOR_DENY_ONLY

        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_broker_close_releases_restricted_token_idempotently(self):
        """Native token ownership must be explicit and cleanup idempotent."""
        import shutil

        workspace = tempfile.mkdtemp(prefix="iso_close_test_")
        broker = create_default_isolation(workspace)
        try:
            broker.initialize()
            token = broker.restricted_token
            assert token is not None
            assert int(token) != 0

            broker.close()
            assert broker.restricted_token is None
            assert int(token) == 0
            broker.close()
        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_workspace_dacl_is_protected_and_has_required_inheritable_aces(self):
        """Workspace ACL must be a real protected DACL for all required SIDs."""
        import shutil

        import ntsecuritycon
        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_acl_test_")
        broker = WindowsIsolationBroker(
            IsolationConfig(workspace_root=workspace, enable_restricted_token=False)
        )
        try:
            boundary = broker.initialize()
            descriptor = win32security.GetNamedSecurityInfo(
                workspace,
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            control, _revision = descriptor.GetSecurityDescriptorControl()
            assert control & win32security.SE_DACL_PROTECTED

            host_sids = {
                win32security.ConvertSidToStringSid(broker._current_user_sid()),
                win32security.ConvertSidToStringSid(
                    win32security.CreateWellKnownSid(
                        win32security.WinLocalSystemSid,
                        None,
                    )
                ),
                win32security.ConvertSidToStringSid(
                    win32security.CreateWellKnownSid(
                        win32security.WinBuiltinAdministratorsSid,
                        None,
                    )
                ),
            }
            assert boundary.appcontainer_sid is not None
            required_sids = host_sids | {boundary.appcontainer_sid}
            inheritance = (
                win32security.OBJECT_INHERIT_ACE
                | win32security.CONTAINER_INHERIT_ACE
            )
            dacl = descriptor.GetSecurityDescriptorDacl()
            matching_sids = set()
            for index in range(dacl.GetAceCount()):
                ace = dacl.GetAce(index)
                ace_type, ace_flags = ace[0]
                sid_text = win32security.ConvertSidToStringSid(ace[2])
                required_mask = (
                    ntsecuritycon.FILE_ALL_ACCESS
                    if sid_text in host_sids
                    else (
                        ntsecuritycon.FILE_GENERIC_READ
                        | ntsecuritycon.FILE_GENERIC_WRITE
                        | ntsecuritycon.FILE_GENERIC_EXECUTE
                        | ntsecuritycon.DELETE
                    )
                )
                if (
                    ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE
                    and ace_flags & inheritance == inheritance
                    and ace[1] & required_mask == required_mask
                ):
                    matching_sids.add(sid_text)
            assert required_sids <= matching_sids
        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_broker_close_restores_original_workspace_dacl_idempotently(self):
        """Closing the broker must remove the AppContainer workspace grant."""
        import shutil

        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_acl_restore_test_")
        broker = WindowsIsolationBroker(
            IsolationConfig(workspace_root=workspace, enable_restricted_token=False)
        )
        try:
            before = win32security.GetNamedSecurityInfo(
                workspace,
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            before_control, _revision = before.GetSecurityDescriptorControl()
            before_signature = broker._dacl_ace_signature(
                before.GetSecurityDescriptorDacl()
            )

            broker.initialize()
            broker.close()
            broker.close()

            after = win32security.GetNamedSecurityInfo(
                workspace,
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            after_control, _revision = after.GetSecurityDescriptorControl()
            assert bool(before_control & win32security.SE_DACL_PROTECTED) == bool(
                after_control & win32security.SE_DACL_PROTECTED
            )
            assert before_signature == broker._dacl_ace_signature(
                after.GetSecurityDescriptorDacl()
            )
        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_component_aware_deny_path_overlap_validation(self):
        """Sibling names with a common prefix must not be treated as overlap."""
        import shutil

        parent = tempfile.mkdtemp(prefix="iso_overlap_test_")
        workspace = os.path.join(parent, "task")
        sibling = os.path.join(parent, "task-other")
        os.mkdir(workspace)
        os.mkdir(sibling)
        broker = WindowsIsolationBroker(
            IsolationConfig(
                workspace_root=workspace,
                deny_paths=(sibling,),
                enable_restricted_token=False,
            )
        )
        try:
            assert broker.initialize().workspace_acl_applied
        finally:
            broker.close()
            shutil.rmtree(parent, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    @pytest.mark.parametrize("deny_location", ["parent", "child"])
    def test_workspace_and_deny_path_parent_child_overlap_fails_closed(
        self, deny_location: str,
    ):
        """A deny path cannot be an ancestor or descendant of the workspace."""
        import shutil

        parent = tempfile.mkdtemp(prefix="iso_overlap_reject_test_")
        workspace = os.path.join(parent, "task")
        child = os.path.join(workspace, "denied")
        os.makedirs(child)
        deny_path = parent if deny_location == "parent" else child
        broker = WindowsIsolationBroker(
            IsolationConfig(
                workspace_root=workspace,
                deny_paths=(deny_path,),
                enable_restricted_token=False,
            )
        )
        try:
            with pytest.raises(Exception, match="deny_path overlaps workspace"):
                broker.initialize()
        finally:
            broker.close()
            shutil.rmtree(parent, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_failure_after_workspace_acl_application_restores_original_dacl(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """Initialization failure after SetNamedSecurityInfo must roll back."""
        import shutil

        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_acl_rollback_test_")
        broker = WindowsIsolationBroker(
            IsolationConfig(workspace_root=workspace, enable_restricted_token=False)
        )
        before = win32security.GetNamedSecurityInfo(
            workspace,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        before_control, _revision = before.GetSecurityDescriptorControl()
        before_signature = broker._dacl_ace_signature(
            before.GetSecurityDescriptorDacl()
        )

        def fail_verification(_workspace: str, _required_sids: set[str]) -> None:
            raise RuntimeError("forced post-ACL verification failure")

        monkeypatch.setattr(broker, "_verify_workspace_acl", fail_verification)
        try:
            with pytest.raises(
                Exception,
                match="forced post-ACL verification failure",
            ):
                broker.initialize()

            after = win32security.GetNamedSecurityInfo(
                workspace,
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            after_control, _revision = after.GetSecurityDescriptorControl()
            assert bool(before_control & win32security.SE_DACL_PROTECTED) == bool(
                after_control & win32security.SE_DACL_PROTECTED
            )
            assert before_signature == broker._dacl_ace_signature(
                after.GetSecurityDescriptorDacl()
            )
            assert broker._workspace_acl_snapshot is None
        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_initialize_fails_closed_on_invalid_workspace(self):
        """Initialization must fail-closed on invalid workspace."""
        broker = create_default_isolation("C:\\nonexistent\\path\\that\\does\\not\\exist")

        with pytest.raises(Exception, match="isolation initialization failed"):
            broker.initialize()
        assert broker.restricted_token is None

    def test_initialize_fails_closed_off_windows(self):
        """On non-Windows, initialization must fail-closed."""
        if sys.platform == "win32":
            pytest.skip("host-dependent")
        broker = create_default_isolation("/tmp")
        with pytest.raises(Exception):
            broker.initialize()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_workspace_acl_covers_existing_children_and_restores_each_dacl(self):
        """Existing nested workspace items receive access and restore exactly."""

        import shutil

        import ntsecuritycon
        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_recursive_acl_")
        nested = os.path.join(workspace, "nested")
        os.makedirs(nested)
        child = os.path.join(nested, "child.txt")
        with open(child, "w", encoding="utf-8") as stream:
            stream.write("workspace")

        broker = WindowsIsolationBroker(
            IsolationConfig(workspace_root=workspace, enable_restricted_token=False)
        )
        paths = (workspace, nested, child)
        before = {
            path: broker._snapshot_acl(path)
            for path in paths
        }
        try:
            boundary = broker.initialize()
            assert boundary.appcontainer_sid is not None
            package_sid = boundary.appcontainer_sid
            required = (
                ntsecuritycon.FILE_GENERIC_READ
                | ntsecuritycon.FILE_GENERIC_WRITE
                | ntsecuritycon.FILE_GENERIC_EXECUTE
                | ntsecuritycon.DELETE
            )
            for path in paths:
                descriptor = win32security.GetNamedSecurityInfo(
                    path,
                    win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION,
                )
                dacl = descriptor.GetSecurityDescriptorDacl()
                assert dacl is not None
                package_mask = 0
                for index in range(dacl.GetAceCount()):
                    ace = dacl.GetAce(index)
                    if (
                        ace[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE
                        and win32security.ConvertSidToStringSid(ace[2]) == package_sid
                    ):
                        package_mask |= ace[1]
                assert package_mask & required == required
        finally:
            broker.close()
            for path, snapshot in before.items():
                assert broker._snapshot_acl(path).original_sddl == snapshot.original_sddl
                assert broker._snapshot_acl(path).was_protected == snapshot.was_protected
            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_runtime_acl_is_read_execute_only_and_restores_children(self):
        """Trusted runtime trees grant package SID RX without write privileges."""

        import shutil

        import ntsecuritycon
        import win32security

        workspace = tempfile.mkdtemp(prefix="iso_runtime_workspace_")
        runtime = tempfile.mkdtemp(prefix="iso_runtime_root_")
        nested = os.path.join(runtime, "nested")
        os.makedirs(nested)
        child = os.path.join(nested, "runtime.bin")
        with open(child, "wb") as stream:
            stream.write(b"runtime")

        broker = WindowsIsolationBroker(
            IsolationConfig(
                workspace_root=workspace,
                runtime_roots=(runtime,),
                enable_restricted_token=False,
            )
        )
        paths = (runtime, nested, child)
        before = {path: broker._snapshot_acl(path) for path in paths}
        try:
            boundary = broker.initialize()
            assert boundary.appcontainer_sid is not None
            read_execute = (
                ntsecuritycon.FILE_GENERIC_READ
                | ntsecuritycon.FILE_GENERIC_EXECUTE
            )
            forbidden = (
                ntsecuritycon.FILE_WRITE_DATA
                | ntsecuritycon.FILE_APPEND_DATA
                | ntsecuritycon.FILE_WRITE_EA
                | ntsecuritycon.FILE_WRITE_ATTRIBUTES
                | ntsecuritycon.DELETE
                | ntsecuritycon.WRITE_DAC
                | ntsecuritycon.WRITE_OWNER
            )
            for path in paths:
                descriptor = win32security.GetNamedSecurityInfo(
                    path,
                    win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION,
                )
                dacl = descriptor.GetSecurityDescriptorDacl()
                assert dacl is not None
                package_masks = [
                    ace[1]
                    for index in range(dacl.GetAceCount())
                    for ace in [dacl.GetAce(index)]
                    if (
                        ace[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE
                        and win32security.ConvertSidToStringSid(ace[2])
                        == boundary.appcontainer_sid
                    )
                ]
                assert package_masks
                assert all(mask & read_execute == read_execute for mask in package_masks)
                assert all(mask & forbidden == 0 for mask in package_masks)
        finally:
            broker.close()
            for path, snapshot in before.items():
                restored = broker._snapshot_acl(path)
                assert restored.original_sddl == snapshot.original_sddl
                assert restored.was_protected == snapshot.was_protected
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(runtime, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_reparse_point_is_rejected_before_native_side_effects(self, monkeypatch):
        """Workspace reparse points must fail before token/profile/ACL changes."""

        import shutil

        workspace = tempfile.mkdtemp(prefix="iso_reparse_workspace_")
        target = tempfile.mkdtemp(prefix="iso_reparse_target_")
        link = os.path.join(workspace, "link")
        try:
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                pytest.skip(f"symlink creation unavailable: {exc}")

            broker = create_default_isolation(workspace)
            called = []
            monkeypatch.setattr(
                broker,
                "_apply_restricted_token",
                lambda: called.append("token"),
            )
            monkeypatch.setattr(
                broker,
                "_create_appcontainer_profile",
                lambda: called.append("profile"),
            )
            monkeypatch.setattr(
                broker,
                "_apply_workspace_acl",
                lambda: called.append("acl"),
            )

            with pytest.raises(Exception, match="reparse point"):
                broker.initialize()
            assert called == []
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(target, ignore_errors=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_non_empty_egress_allowlist_fails_before_native_side_effects(
        self, monkeypatch,
    ):
        """Allowlist requests fail closed until WFP/proxy enforcement exists."""

        import shutil

        workspace = tempfile.mkdtemp(prefix="iso_egress_workspace_")
        broker = WindowsIsolationBroker(
            IsolationConfig(
                workspace_root=workspace,
                egress_allowlist=("api.example.com:443",),
            )
        )
        called = []
        monkeypatch.setattr(broker, "_apply_restricted_token", lambda: called.append("token"))
        monkeypatch.setattr(
            broker,
            "_create_appcontainer_profile",
            lambda: called.append("profile"),
        )
        monkeypatch.setattr(broker, "_apply_workspace_acl", lambda: called.append("acl"))
        try:
            with pytest.raises(Exception, match="non-empty egress_allowlist"):
                broker.initialize()
            assert called == []
        finally:
            broker.close()
            shutil.rmtree(workspace, ignore_errors=True)


class TestContractConformance:
    """Verify isolation module conforms to shared contracts."""

    def test_isolation_config_is_frozen(self):
        """IsolationConfig must be immutable."""
        config = IsolationConfig(workspace_root="/tmp")
        with pytest.raises((AttributeError, TypeError)):
            config.workspace_root = "/other"  # type: ignore[misc]

    def test_secret_handle_clears_value_after_consume(self):
        """Secret value must be cleared from memory after consume."""
        import time

        handle = SecretHandle(
            handle_id="test-clear",
            tool_name="tool",
            task_id="task",
            created_at=time.time(),
            _value="sensitive-data",
        )

        handle.consume()
        assert handle._value is None

    def test_create_default_isolation_returns_broker(self):
        """create_default_isolation must return a WindowsIsolationBroker."""
        broker = create_default_isolation("/tmp")
        assert isinstance(broker, WindowsIsolationBroker)
        assert broker.config.workspace_root == "/tmp"
