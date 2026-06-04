from agents.healing_agent.executors.ssh_executor import SSHExecutor
from agents.healing_agent.executors.ansible_executor import AnsibleExecutor
from agents.healing_agent.executors.rest_executor import RESTExecutor
from agents.healing_agent.executors.notification_executor import NotificationExecutor


_registry = {
    "ssh":           SSHExecutor,
    "winrm":         SSHExecutor,    # WinRM shares interface, different impl
    "ansible":       AnsibleExecutor,
    "rest":          RESTExecutor,
    "api":           RESTExecutor,
    "notification":  NotificationExecutor,
}


def get_executor(executor_type: str):
    cls = _registry.get(executor_type.lower(), SSHExecutor)
    return cls()
