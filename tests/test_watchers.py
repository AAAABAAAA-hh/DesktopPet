from __future__ import annotations

import unittest

from petapp.watchers import classify_foreground


class WatcherClassificationTests(unittest.TestCase):
    def test_work_app(self) -> None:
        self.assertEqual(classify_foreground("Code.exe", "main.py - Visual Studio Code"), "work")
        self.assertEqual(classify_foreground("pycharm64.exe", "project"), "work")

    def test_game(self) -> None:
        self.assertEqual(classify_foreground("GenshinImpact.exe", "Genshin Impact"), "play")
        self.assertEqual(classify_foreground("javaw.exe", "Minecraft 1.21"), "play")

    def test_browser_video(self) -> None:
        self.assertEqual(
            classify_foreground("chrome.exe", "【合集】高等数学 第 3 讲 - 哔哩哔哩"),
            "play",
        )
        self.assertEqual(
            classify_foreground("msedge.exe", "Python 官方教程 — Microsoft Learn"),
            "work",
        )
        self.assertEqual(classify_foreground("firefox.exe", "GitHub"), "other")

    def test_unknown(self) -> None:
        self.assertEqual(classify_foreground("explorer.exe", "Downloads"), "other")
        self.assertEqual(classify_foreground("", ""), "other")


if __name__ == "__main__":
    unittest.main()
