"""命名约定守卫：字段名 = 环境变量名小写（约定大于配置）。"""

import unittest
from dataclasses import fields

from config import ENV_TO_FIELD, FIELD_TO_ENV, AppConfig


class EnvKeysTest(unittest.TestCase):
    def test_field_equals_env_lowercase(self):
        for f in fields(AppConfig):
            self.assertEqual(FIELD_TO_ENV[f.name], f.name.upper())

    def test_reverse_map(self):
        for field, env in FIELD_TO_ENV.items():
            self.assertEqual(ENV_TO_FIELD[env], field)


if __name__ == "__main__":
    unittest.main()
