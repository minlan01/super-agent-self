#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <iostream>
#include <string>
#include <thread>
#include <vector>

int wmain() {
    HANDLE input_read = nullptr;
    HANDLE input_write = nullptr;
    HANDLE output_read = nullptr;
    HANDLE output_write = nullptr;
    if (!CreatePipe(&input_read, &input_write, nullptr, 0) ||
        !CreatePipe(&output_read, &output_write, nullptr, 0)) {
        std::cerr << "CreatePipe failed: " << GetLastError() << "\n";
        return 10;
    }

    HPCON pseudo_console = nullptr;
    const HRESULT create_hr = CreatePseudoConsole(
        COORD{80, 24}, input_read, output_write, 0, &pseudo_console);
    CloseHandle(input_read);
    CloseHandle(output_write);
    if (FAILED(create_hr)) {
        std::cerr << "CreatePseudoConsole failed: 0x" << std::hex << create_hr << "\n";
        return 11;
    }

    SIZE_T bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
    std::vector<unsigned char> storage(bytes);
    auto attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
    if (!InitializeProcThreadAttributeList(attributes, 1, 0, &bytes)) {
        std::cerr << "InitializeProcThreadAttributeList failed: " << GetLastError() << "\n";
        return 12;
    }
    if (!UpdateProcThreadAttribute(
            attributes,
            0,
            PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            pseudo_console,
            sizeof(pseudo_console),
            nullptr,
            nullptr)) {
        std::cerr << "UpdateProcThreadAttribute failed: " << GetLastError() << "\n";
        return 13;
    }

    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.lpAttributeList = attributes;
    PROCESS_INFORMATION process{};
    wchar_t command[] = L"cmd.exe /d /q";
    if (!CreateProcessW(
            nullptr,
            command,
            nullptr,
            nullptr,
            FALSE,
            EXTENDED_STARTUPINFO_PRESENT,
            nullptr,
            nullptr,
            &startup.StartupInfo,
            &process)) {
        std::cerr << "CreateProcessW failed: " << GetLastError() << "\n";
        return 14;
    }
    CloseHandle(process.hThread);

    std::string output;
    std::thread reader([&]() {
        char buffer[4096];
        DWORD read = 0;
        while (ReadFile(output_read, buffer, sizeof(buffer), &read, nullptr) && read) {
            output.append(buffer, read);
        }
    });

    const std::string command_text = "echo CPP_CONPTY_OK\r\nexit\r\n";
    DWORD written = 0;
    WriteFile(
        input_write,
        command_text.data(),
        static_cast<DWORD>(command_text.size()),
        &written,
        nullptr);
    WaitForSingleObject(process.hProcess, 5000);
    CloseHandle(input_write);

    using ReleasePseudoConsoleFn = HRESULT(WINAPI*)(HPCON);
    const auto release = reinterpret_cast<ReleasePseudoConsoleFn>(
        GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "ReleasePseudoConsole"));
    if (release != nullptr) {
        release(pseudo_console);
    }
    reader.join();
    ClosePseudoConsole(pseudo_console);

    DWORD exit_code = STILL_ACTIVE;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hProcess);
    CloseHandle(output_read);
    DeleteProcThreadAttributeList(attributes);

    const bool found = output.find("CPP_CONPTY_OK") != std::string::npos;
    std::cout << "exit_code=" << exit_code << "\n";
    std::cout << "output_bytes=" << output.size() << "\n";
    std::cout << "marker_found=" << (found ? "true" : "false") << "\n";
    return found ? 0 : 15;
}
