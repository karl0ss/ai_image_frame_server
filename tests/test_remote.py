import io

import libs.remote as remote


class Channel:
    def recv_exit_status(self):
        return 0


class Stream(io.BytesIO):
    channel = Channel()


class FakeClient:
    def __init__(self):
        self.commands = []
        self.stdin = io.StringIO()

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        return self.stdin, Stream(b"active"), Stream(b"")


def test_sudo_password_stays_off_the_command_line():
    manager = remote.ComfyUIRemoteManager("host", "user", "pa'ss", "comfyui")
    manager._client = client = FakeClient()
    manager._sudo("systemctl start comfyui")
    assert client.commands == ["sudo -S -p '' systemctl start comfyui"]
    assert client.stdin.getvalue() == "pa'ss\n"
