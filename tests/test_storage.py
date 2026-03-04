import unittest

import os
import shutil
import tempfile

from gomoku_lan.storage import Settings, _release_runtime_locks_for_tests, allocate_runtime_settings


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="gomoku-lan-test-")
        os.environ["GOMOKU_LAN_DATA_DIR"] = self._tmp

    def tearDown(self) -> None:
        _release_runtime_locks_for_tests()
        try:
            shutil.rmtree(self._tmp)
        except Exception:
            pass
        os.environ.pop("GOMOKU_LAN_DATA_DIR", None)

    def test_allocate_runtime_settings_second_instance(self) -> None:
        base = Settings(peer_id="peer-fixed", nickname="玩家A")
        s1, ep1 = allocate_runtime_settings(base)
        s2, ep2 = allocate_runtime_settings(base)

        self.assertFalse(ep1)
        self.assertTrue(ep2)
        self.assertEqual(s1.peer_id, "peer-fixed")
        self.assertNotEqual(s2.peer_id, "peer-fixed")
        self.assertNotEqual(s2.peer_id, s1.peer_id)


if __name__ == "__main__":
    unittest.main()
