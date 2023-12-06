import asyncio
import json
import os

from bitwardenproject import BitwardenProject
from bitwardensyncerror import BitwardenSyncError

class BitwardenProjects:
    bws_cmd = os.environ.get('BWS_CMD', 'bws')

    @classmethod
    async def get(cls, access_token):
        proc = await asyncio.create_subprocess_exec(
            cls.bws_cmd, '--access-token', access_token, '--output', 'json', 'project', 'list',
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            raise BitwardenSyncError(f"bws error on project list: {stderr}")
        return cls(json.loads(stdout))

    def __init__(self, projects):
        self.projects_dict = {
            project['name']: BitwardenProject(project) for project in projects
        }

    def get_project(self, project_name):
        return self.projects_dict.get(project_name)
