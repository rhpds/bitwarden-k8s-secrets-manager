from bitwardensecret import BitwardenSecret

class BitwardenSecrets:
    bws_cmd = os.environ.get('BWS_CMD', 'bws')

    @classmethod
    async def get(cls, access_token):
        proc = await asyncio.create_subprocess_exec(
            cls.bws_cmd, '--access-token', access_token, '--output', 'json', 'list', 'secrets',
            stdout = asyncio.subprocess.PIPE,
            stderr = asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            raise BitwardenSyncError(f"bws error: {stderr}")

        return cls(
            secrets_dict = {
                item['key']: BitwardenSecret(item) for item in json.loads(stdout)
            }
        )

    def __init__(self, secrets_dict):
        self.secrets_dict = secrets_dict

    def get_values(self, secret_sources):
        ret = {}
        for key, src in secret_sources.items():
            if src.value:
                ret[key] = src.value
            elif src.secret:
                if src.secret not in self.secrets_dict:
                    raise BitwardenSyncError(f"No Bitwarden secret {src.secret}")
                value = self.secrets_dict[src.secret].value
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
