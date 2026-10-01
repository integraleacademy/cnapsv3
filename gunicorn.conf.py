# Keep ordinary form/admin requests responsive while an optional API check waits.
# The analysis endpoint separately limits concurrent checks and daily usage.
threads = 4
timeout = 60
