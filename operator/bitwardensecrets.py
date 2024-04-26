from base64 import b64encode

import asyncio
import json
import os

from bitwardensecret import BitwardenSecret
from bitwardensyncerror import BitwardenSyncError

class BitwardenSecrets:
    bws_cmd = os.environ.get('BWS_CMD', 'bws')

    @classmethod
    async def get(cls, access_token, project_id=None):
        cmd = [cls.bws_cmd, '--access-token', access_token, '--output', 'json', 'secret', 'list']
        if project_id:
            cmd.append(project_id)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            raise BitwardenSyncError(f"bws error: {stderr}")
        return cls(json.loads(stdout))

    def __init__(self, secrets):
        self.secrets = [BitwardenSecret(item) for item in secrets]

    def __get_value(self, secret_key, project):
        for secret in self.secrets:
            if project and secret.project_id != project.id:
                continue
            if secret.key == secret_key:
                return secret.value
        if project:
            raise BitwardenSyncError(
                f"Bitwarden secret \"{secret_key}\" not found in project {project}"
            )
        raise BitwardenSyncError(f"Bitwarden secret \"{secret_key}\" not found")

    def get_values(self, sources, projects, for_data=False):
        ret = {}
        for key, src in sources.items():
            base64encode = for_data and src.base64encode
            project = None
            if src.project:
                project = projects.get_project(src.project)
                if not project:
                    raise BitwardenSyncError(
                        f"Bitwarden project \"{src.project}\" not found"
                    )

            if src.value:
                ret[key] = b64encode(src.value.encode('utf-8')).decode('utf-8') if base64encode else src.value
            elif src.secret:
                value = self.__get_value(src.secret, project)
                if src.key:
                    if not isinstance(value, dict):
                        raise BitwardenSyncError(
                            f"Bitwarden secret {src.secret} not in YAML dictionary format for {src.key}"
                        )
                    # Check for key like `tls.key` at top level and use it if set.
                    if src.key in value:
                        value = value[src.key]
                    # Otherwise treat as deep key with `.` delimiters
                    else:
                        for item in src.key.split('.'):
                            if not isinstance(value, dict):
                                raise BitwardenSyncError(
                                    f"Bitwarden secret {src.secret} not in YAML dictionary format for {src.key}"
                                )
                            if item not in value:
                                raise BitwardenSyncError(
                                    f"Bitwarden secret {src.secret} has no key {src.key}"
                                )
                            value = value[item]
                if not isinstance(value, str):
                    # Maybe not what is intended, but better than to fail?
                    value = json.dumps(value)
                ret[key] = b64encode(value.encode('utf-8')).decode('utf-8') if base64encode else value
            else:
                raise BitwardenSyncError("No secret or value in configuration")
        return ret
