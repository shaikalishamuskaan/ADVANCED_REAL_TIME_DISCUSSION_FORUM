import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from dotenv import dotenv_values

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap.py"
spec = importlib.util.spec_from_file_location("forum_bootstrap", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def setup(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            module.bootstrap(self.root)
        return output.getvalue()

    def snapshot(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob('*') if path.is_file()}

    def test_first_run_creates_matching_configuration_without_printing_secrets(self):
        output = self.setup()
        root = dotenv_values(self.root / '.env')
        docker = dotenv_values(self.root / '.env.docker')
        self.assertRegex(root['COMPOSE_PROJECT_NAME'], r'^forum-[0-9a-f]{12}$')
        self.assertEqual(root['COMPOSE_PROJECT_NAME'], docker['COMPOSE_PROJECT_NAME'])
        self.assertEqual(root['POSTGRES_PASSWORD'], docker['POSTGRES_PASSWORD'])
        keys = json.loads(root['SERVICE_API_KEYS'])
        self.assertEqual(set(keys), {'discussion','notify','realtime'})
        self.assertEqual(len(set(keys.values())),3)
        for value in [root['POSTGRES_PASSWORD'],root['DJANGO_SECRET_KEY'],root['RECOVERY_CODE_HMAC_KEY'],*keys.values()]:
            self.assertGreaterEqual(len(value),32)
            self.assertNotIn(value,output)
        self.assertEqual(docker['DISCUSSION_SERVICE_KEY'],keys['discussion'])
        for service in ['discussion','search']:
            config=dotenv_values(self.root / 'services' / service / '.env')
            self.assertEqual(config['SEARCH_SERVICE_KEY'],root['SEARCH_SERVICE_KEY'])
        self.assertTrue((self.root/'services/identity/keys/jwt-private.pem').is_file())

    def test_repeated_setup_preserves_every_generated_value_and_key(self):
        self.setup()
        before=self.snapshot()
        self.setup()
        self.assertEqual(before,self.snapshot())

    def test_existing_configuration_with_missing_keys_is_not_rotated(self):
        module.write_missing(self.root/'.env', {name:'configured-value' for name in module.REQUIRED})
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'missing JWT keys'):
            self.setup()
        self.assertEqual(before,self.snapshot())

    def test_keys_without_root_configuration_are_not_overwritten(self):
        path=self.root/'services/identity/keys/jwt-private.pem'
        path.parent.mkdir(parents=True)
        path.write_text('existing-private-material')
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Existing JWT keys'):
            self.setup()
        self.assertEqual(before,self.snapshot())

    def test_custom_ports_survive_regeneration(self):
        self.setup()
        with (self.root/'.env').open('a') as output:
            output.write("FRONTEND_HOST_PORT=18080\nPOSTGRES_HOST_PORT=15433\nREDIS_HOST_PORT=16380\n")
        self.setup()
        docker=dotenv_values(self.root/'.env.docker')
        self.assertEqual(docker['FRONTEND_HOST_PORT'],'18080')
        self.assertEqual(docker['POSTGRES_HOST_PORT'],'15433')
        self.assertEqual(docker['REDIS_HOST_PORT'],'16380')

    def test_conflicting_export_key_is_rejected_without_overwriting_files(self):
        self.setup()
        with (self.root/'services/search/.env').open('a') as output:
            output.write("SEARCH_SERVICE_KEY='conflicting-development-value'\n")
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'disagree'):
            self.setup()
        self.assertEqual(before,self.snapshot())

    def test_independent_checkouts_get_distinct_projects_and_credentials(self):
        self.setup()
        other = self.root / 'another-checkout'
        with contextlib.redirect_stdout(io.StringIO()):
            module.bootstrap(other)
        first = dotenv_values(self.root / '.env.docker')
        second = dotenv_values(other / '.env.docker')
        for name in ('COMPOSE_PROJECT_NAME', 'POSTGRES_PASSWORD', 'DJANGO_SECRET_KEY'):
            self.assertNotEqual(first[name], second[name])

    def test_new_instance_options_are_persisted_and_cannot_retarget_existing_data(self):
        options = dict(project_name='forum-mentor-test', frontend_port=18081, postgres_port=15434, redis_port=16381)
        with contextlib.redirect_stdout(io.StringIO()):
            module.bootstrap(self.root, **options)
        config = dotenv_values(self.root / '.env.docker')
        self.assertEqual(config['COMPOSE_PROJECT_NAME'], 'forum-mentor-test')
        self.assertEqual(config['FRONTEND_HOST_PORT'], '18081')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Existing instance was preserved'):
            module.bootstrap(self.root, project_name='another-project')
        self.assertEqual(before, self.snapshot())

    def test_invalid_instance_options_write_nothing(self):
        for options in (dict(project_name='../unsafe'), dict(frontend_port=0), dict(redis_port=65536)):
            with self.assertRaises(ValueError):
                module.bootstrap(self.root, **options)
            self.assertEqual(self.snapshot(), {})
