import lease

def test_low_granted_only_when_idle():
    assert lease.acquire_gpu("cust", "c", priority="low") is True
    assert lease.gpu_is_idle() is True            # only a low holder => idle
    lease.release_gpu("cust")

def test_low_busy_when_normal_holds():
    assert lease.acquire_gpu("job", "t", priority="normal") is True
    assert lease.gpu_is_idle() is False
    assert lease.acquire_gpu("cust", "c", priority="low", wait=False) is False
    lease.release_gpu("job")

def test_normal_flags_revoke_on_low():
    assert lease.acquire_gpu("cust", "c", priority="low") is True
    # normal acquirer flags revoke then (wait=False) returns without stealing
    assert lease.acquire_gpu("job", "t", priority="normal", wait=False) is False
    assert lease.is_revoked("cust") is True
    lease.release_gpu("cust")

def test_normal_force_steals_low_after_grace():
    assert lease.acquire_gpu("cust", "c", priority="low") is True
    assert lease.acquire_gpu("job", "t", priority="normal", grace=0.05, timeout=2) is True
    assert lease.gpu_lease_status()["holder"] == "job"
    lease.release_gpu("job")

def test_normal_vs_normal_still_busy():
    assert lease.acquire_gpu("a", "t", priority="normal") is True
    assert lease.acquire_gpu("b", "t", priority="normal", wait=False) is False
    lease.release_gpu("a")
