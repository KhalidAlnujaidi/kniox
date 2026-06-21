import classifier
from jobspec import Job

FACTS = {"worker_free_mem_gb": 7.0}

def test_gpu_job_pinned_to_enigma():
    assert classifier.classify(Job(task="t", needs_gpu=True), FACTS)["placement"] == "enigma-gpu"

def test_local_paths_force_enigma_local():
    r = classifier.classify(Job(task="t", local_paths=["/home/x"]), FACTS)
    assert r["placement"] == "enigma-local"

def test_interactive_forces_enigma_local():
    assert classifier.classify(Job(task="t", interactive=True), FACTS)["placement"] == "enigma-local"

def test_big_mem_forces_enigma_local():
    assert classifier.classify(Job(task="t", est_mem_gb=16), FACTS)["placement"] == "enigma-local"

def test_plain_cpu_job_goes_to_cluster():
    assert classifier.classify(Job(task="t"), FACTS)["placement"] == "cluster"

def test_header_cluster_honored():
    assert classifier.classify(Job(task="t", placement="cluster"), FACTS)["placement"] == "cluster"

def test_safety_rule_header_cluster_but_local_paths_downgrades():
    r = classifier.classify(Job(task="t", placement="cluster", local_paths=["/x"]), FACTS)
    assert r["placement"] == "enigma-local"
    assert "local_paths" in r["reason"]

def test_unknown_worker_mem_does_not_block_small_job():
    assert classifier.classify(Job(task="t"), {"worker_free_mem_gb": None})["placement"] == "cluster"
