import csv
import json

import cv2

from portrait_qa.cli import main

from .conftest import IMAGES


def test_assess_exit_codes(tmp_path, capsys):
    cfg = tmp_path / "config.json"
    assert main(["--config", str(cfg), "assess", str(IMAGES / "astronaut.png")]) == 0
    line = json.loads(capsys.readouterr().out)
    assert line["passed"] is True
    assert main(["--config", str(cfg), "assess", str(IMAGES / "cat.png")]) == 1
    assert main(["--config", str(cfg), "assess", str(tmp_path / "missing.jpg")]) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["error"] == "IO_ERROR"


def test_crop(tmp_path, capsys):
    out = tmp_path / "face.jpg"
    code = main(["--config", str(tmp_path / "c.json"), "crop", str(IMAGES / "astronaut.png"), "-o", str(out),
                 "-p", "badge"])  # fmt: skip
    assert code == 0
    assert cv2.imread(str(out)).shape[:2] == (400, 300)
    assert json.loads(capsys.readouterr().out)["crop"]["profile"] == "badge"


def test_crop_without_face(tmp_path, capsys):
    code = main(["--config", str(tmp_path / "c.json"), "crop", str(IMAGES / "cat.png"), "-o", str(tmp_path / "x.jpg")])
    assert code == 2
    assert "No face" in capsys.readouterr().err


def test_batch(tmp_path, variants, capsys):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    cv2.imwrite(str(src / "good.png"), variants["large"])
    cv2.imwrite(str(src / "sub" / "blurry.jpg"), variants["blurry"])
    cv2.imwrite(str(src / "cat.jpg"), cv2.imread(str(IMAGES / "cat.png")))
    (src / "notes.txt").write_text("ignored")
    (src / "broken.jpg").write_bytes(b"\xff\xd8\xff garbage")
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "c.json"), "batch", str(src), "-o", str(out), "-q"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"files": 4, "passed": 1, "failed": 2, "error": 1, "report": str(out / "portrait-qa-report.csv")}
    rows = {r["file"]: r for r in csv.DictReader((out / "portrait-qa-report.csv").open(encoding="utf-8"))}
    assert rows["good.png"]["cropped"] == "good.jpg" and (out / "good.jpg").exists()
    assert "BLURRY" in rows["sub/blurry.jpg"]["issues"].split()
    assert rows["broken.jpg"]["error"].startswith("INVALID_IMAGE")


def test_bad_config_is_reported(tmp_path, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"server": {"port": "x"}}')
    assert main(["--config", str(cfg), "assess", str(IMAGES / "astronaut.png")]) == 2
    assert "server.port must be int" in capsys.readouterr().err


def test_assess_keeps_the_worst_exit_code(tmp_path, capsys):
    cfg = str(tmp_path / "c.json")
    assert main(["--config", cfg, "assess", str(tmp_path / "missing.jpg"), str(IMAGES / "cat.png")]) == 2


def test_crop_creates_the_output_folder(tmp_path, capsys):
    out = tmp_path / "new" / "dir" / "face.jpg"
    assert main(["--config", str(tmp_path / "c.json"), "crop", str(IMAGES / "astronaut.png"), "-o", str(out)]) == 0
    assert out.exists()


def test_batch_does_not_overwrite_crops_with_the_same_stem(tmp_path, variants, capsys):
    src = tmp_path / "in"
    src.mkdir()
    cv2.imwrite(str(src / "a.png"), variants["large"])
    cv2.imwrite(str(src / "a.jpg"), variants["large"])
    cv2.imwrite(str(src / "b.png"), variants["large"])
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "c.json"), "batch", str(src), "-o", str(out), "-q"]) == 0
    rows = {r["file"]: r["cropped"] for r in csv.DictReader((out / "portrait-qa-report.csv").open(encoding="utf-8"))}
    assert rows == {"a.jpg": "a.jpg.jpg", "a.png": "a.png.jpg", "b.png": "b.jpg"}
    assert all((out / name).exists() for name in rows.values())
