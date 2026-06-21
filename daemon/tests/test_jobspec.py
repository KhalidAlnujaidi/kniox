import jobspec

def test_defaults_are_safe():
    j = jobspec.Job(task="x")
    assert j.needs_gpu is False and j.local_paths == [] and j.placement is None

def test_from_script_reads_header(tmp_path):
    f = tmp_path / "job.py"
    f.write_text("# kniox: placement=cluster mem=2G\nimport os\n")
    j = jobspec.Job.from_script(str(f), task="scrape")
    assert j.placement == "cluster" and j.command == ["uv", "run", str(f)]
    assert j.est_mem_gb == 2.0
    assert "import os" in j.source

def test_from_script_no_header_leaves_placement_none(tmp_path):
    f = tmp_path / "job.py"
    f.write_text("import os\n")
    j = jobspec.Job.from_script(str(f))
    assert j.placement is None
