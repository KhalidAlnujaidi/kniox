import time
import lease

def test_acquire_and_release(monkeypatch):
    assert lease.acquire_gpu("a", "text") is True
    assert lease.gpu_lease_status()["holder"] == "a"
    lease.release_gpu("a")
    assert lease.gpu_lease_status() is None

def test_second_holder_blocked_until_timeout():
    assert lease.acquire_gpu("a", "text") is True
    assert lease.acquire_gpu("b", "img", wait=True, timeout=0.2) is False
    lease.release_gpu("a")

def test_expired_lease_is_reclaimed():
    assert lease.acquire_gpu("a", "text", ttl=0) is True
    time.sleep(0.01)
    assert lease.acquire_gpu("b", "img", wait=False) is True   # a's lease expired
    lease.release_gpu("b")
