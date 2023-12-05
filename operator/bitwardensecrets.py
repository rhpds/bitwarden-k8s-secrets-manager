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

        return cls(
            secrets = [BitwardenSecret(item) for item in json.loads(stdout)]
        )

    def __init__(self, secrets):
        self.secrets = secrets

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

    def get_values(self, sources, projects):
        ret = {}
        for key, src in sources.items():
            project = None
            if src.project:
                project = projects.get_project(src.project)
                if not project:
                    raise BitwardenSyncError(
                        f"Bitwarden project \"{src.project}\" not found"
                    )

            if src.value:
                ret[key] = src.value
            elif src.secret:
                value = self.__get_value(src.secret, project)
                if src.key:
                    if not isinstance(value, dict):
                        raise BitwardenSyncError(
                            f"Bitwarden secret {src.secret} not in YAML dictionary format"
                        )
                    if src.key not in value:
                        raise BitwardenSyncError(
                            f"Bitwarden secret {src.secret} has no key {src.key}"
                        )
                    value = value[src.key]
                if isinstance(value, str):
                    ret[key] = value
                else:
                    # Maybe not what is intended, but better than to fail?
                    ret[key] = json.dumps(value)
            else:
                raise BitwardenSyncError("No secret or value in configuration")
        return ret
