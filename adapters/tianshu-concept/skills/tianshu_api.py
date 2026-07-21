#!/usr/bin/env python3
"""
天枢院 API 集成工具

为天枢院 Agent 提供 API 调用能力：
- 推进任务状态
- 更新任务输出
- 记录进度
- 添加评论
"""

import json
import urllib.request
import urllib.error
import pathlib
from typing import Optional, Dict, Any

BASE_URL = "http://127.0.0.1:7892"


def api_request(endpoint: str, method: str = 'GET', data: Optional[Dict] = None) -> Dict:
    """发送 API 请求"""
    url = f"{BASE_URL}{endpoint}"
    
    headers = {'Content-Type': 'application/json'}
    
    if data and method in ('POST', 'PUT'):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    else:
        body = None
    
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'ok': False, 'error': f'HTTP {e.code}: {e.reason}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def advance_task(task_id: str) -> Dict:
    """推进任务到下一阶段"""
    return api_request(f'/api/task/{task_id}/advance', method='POST')


def stop_task(task_id: str, reason: str) -> Dict:
    """叫停任务"""
    return api_request(f'/api/task/{task_id}/stop', method='POST', data={'reason': reason})


def cancel_task(task_id: str, reason: str) -> Dict:
    """取消任务"""
    return api_request(f'/api/task/{task_id}/cancel', method='POST', data={'reason': reason})


def add_comment(task_id: str, author: str, content: str) -> Dict:
    """添加任务评论"""
    return api_request(f'/api/task/{task_id}/comments', method='POST', data={
        'action': 'add',
        'author': author,
        'content': content
    })


def add_time_tracking(task_id: str, agent: str, hours: float, description: str) -> Dict:
    """记录工时"""
    return api_request(f'/api/task/{task_id}/time', method='POST', data={
        'action': 'add',
        'agent': agent,
        'hours': hours,
        'description': description
    })


def get_task(task_id: str) -> Dict:
    """获取任务详情"""
    return api_request(f'/api/task/{task_id}')


def get_tasks(state: Optional[str] = None) -> Dict:
    """获取任务列表"""
    endpoint = '/api/tasks'
    if state:
        endpoint += f'?state={state}'
    return api_request(endpoint)


# 快捷函数 - 用于 Agent 自动处理
def process_and_advance(task_id: str, agent_name: str, output: str, hours: float = 1.0):
    """
    处理任务并自动推进
    
    Args:
        task_id: 任务 ID
        agent_name: Agent 名称（如：承旨司、中书局等）
        output: 处理输出内容
        hours: 耗时（小时）
    
    Returns:
        Dict: API 响应结果
    """
    # 1. 添加评论（处理结果）
    comment_result = add_comment(task_id, agent_name, output)
    
    # 2. 记录工时
    time_result = add_time_tracking(task_id, agent_name, hours, f'{agent_name}处理任务')
    
    # 3. 推进任务
    advance_result = advance_task(task_id)
    
    return {
        'ok': advance_result.get('ok', False),
        'comment': comment_result,
        'time': time_result,
        'advance': advance_result
    }


if __name__ == '__main__':
    # 测试
    print("天枢院 API 工具测试")
    print("=" * 50)
    
    # 获取任务列表
    tasks = get_tasks()
    print(f"任务总数：{len(tasks)}")
    
    if tasks:
        task = tasks[0]
        print(f"\n测试任务：{task['id']}")
        print(f"状态：{task['state']}")
        print(f"标题：{task['title']}")
