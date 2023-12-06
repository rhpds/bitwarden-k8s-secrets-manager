#!/usr/bin/env python

import unittest
import sys
sys.path.append('../../operator')

from bitwardensyncconfigsecretsource import BitwardenSyncConfigSecretSource
from bitwardenprojects import BitwardenProjects
from bitwardensecrets import BitwardenSecrets

bitwarden_projects = BitwardenProjects([{
    "id": "00000000-0000-0000-0000-000000000000",
    "organizationId": "00000000-0000-0000-0000-000000000000",
    "name": "project0",
    "creationDate": "1970-01-01T00:00:00.000000000Z",
    "revisionDate": "1970-01-01T00:00:00.000000000Z",
}])

bitwarden_secrets = BitwardenSecrets([{
    "id": "00000000-0000-0000-0000-000000000000",
    "organizationId": "00000000-0000-0000-0000-000000000000",
    "projectId": "00000000-0000-0000-0000-000000000000",
    "key": "simple_secret",
    "value": "string value",
    "note": "",
    "creationDate": "1970-01-01T00:00:00.000000000Z",
    "revisionDate": "1970-01-01T00:00:00.000000000Z",
}, {
    "id": "00000000-0000-0000-0000-000000000000",
    "organizationId": "00000000-0000-0000-0000-000000000000",
    "projectId": "00000000-0000-0000-0000-000000000000",
    "key": "dict_secret",
    "value": '''
        {
            "key00": "dict value",
            "key.with.periods": "value not nested",
            "nested": {"key01": "nested value"}
        }
    ''',
    "note": "",
    "creationDate": "1970-01-01T00:00:00.000000000Z",
    "revisionDate": "1970-01-01T00:00:00.000000000Z",
}])

class TestBitwardenSecrets(unittest.TestCase):

    def test_00(self):
        sources = {
            "simple_secret": BitwardenSyncConfigSecretSource({
                "secret": "simple_secret",
            }),
        }
        self.assertEqual(
            bitwarden_secrets.get_values(sources, bitwarden_projects),
            {"simple_secret": "string value"},
        )

    def test_01(self):
        sources = {
            "value-pass-through": BitwardenSyncConfigSecretSource({
                "value": "value pass-through",
            }),
        }
        self.assertEqual(
            bitwarden_secrets.get_values(sources, bitwarden_projects),
            {"value-pass-through": "value pass-through"},
        )

    def test_02(self):
        sources = {
            "secret-with-key": BitwardenSyncConfigSecretSource({
                "key": "key00",
                "secret": "dict_secret",
            }),
        }
        self.assertEqual(
            bitwarden_secrets.get_values(sources, bitwarden_projects),
            {"secret-with-key": "dict value"},
        )

    def test_03(self):
        sources = {
            "secret-with-key": BitwardenSyncConfigSecretSource({
                "key": "nested.key01",
                "secret": "dict_secret",
            }),
        }
        self.assertEqual(
            bitwarden_secrets.get_values(sources, bitwarden_projects),
            {"secret-with-key": "nested value"},
        )

    def test_04(self):
        sources = {
            "value": BitwardenSyncConfigSecretSource({
                "key": "key.with.periods",
                "secret": "dict_secret",
            }),
        }
        self.assertEqual(
            bitwarden_secrets.get_values(sources, bitwarden_projects),
            {"value": "value not nested"},
        )


if __name__ == '__main__':
    unittest.main()
