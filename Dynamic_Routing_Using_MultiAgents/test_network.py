"""Run with: python -m unittest -v"""
import json
from pathlib import Path
import tempfile
import unittest
from network import Network


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.net = Network()
        self.net.add_device("PC-A", "PC")
        self.net.add_device("Core", "ROUTER")

    def test_custom_names_and_defaults(self):
        self.assertEqual(self.net.devices["PC-A"].capacity, 5)
        self.net.add_device("Server-X", "SERVER", 12, 20)
        self.assertEqual(self.net.devices["Server-X"].queue_limit, 20)

    def test_reject_invalid_devices(self):
        with self.assertRaises(ValueError):
            self.net.add_device("Core", "ROUTER")
        with self.assertRaises(ValueError):
            self.net.add_device("Bad", "HUB")

    def test_connect_and_modify(self):
        self.net.connect("PC-A", "Core", 2.5, 50)
        self.assertEqual(self.net.links[("Core", "PC-A")].delay, 2.5)
        self.net.set_link_status("Core", "PC-A", False)
        self.assertFalse(self.net.links[("Core", "PC-A")].enabled)

    def test_reject_invalid_links(self):
        with self.assertRaises(ValueError):
            self.net.connect("PC-A", "Missing")
        with self.assertRaises(ValueError):
            self.net.connect("PC-A", "Core", delay=0)

    def test_remove_device_removes_links(self):
        self.net.connect("PC-A", "Core", 1, 100)
        self.net.remove_device("Core")
        self.assertEqual(len(self.net.links), 0)

    def test_save_load(self):
        self.net.connect("PC-A", "Core", 3, 100)
        self.net.set_device_status("Core", False)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "test.json")
            self.net.save(path)
            copy = Network.load(path)
            self.assertEqual(len(copy.devices), 2)
            self.assertFalse(copy.devices["Core"].online)
            self.assertEqual(copy.links[("Core", "PC-A")].delay, 3)


if __name__ == "__main__":
    unittest.main()
