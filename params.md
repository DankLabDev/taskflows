


| Setting                          | `systemd`                       | `docker`                       | Notes                                              |
| -------------------------------- | ------------------------------- | ------------------------------ | -------------------------------------------------- |
| **Memory limit**                 | `MemoryMax=`                    | `--memory` or `--memory-limit` | Hard memory limit                                  |
| **Memory reservation**           | `MemoryLow=` / `MemoryMin=`     | `--memory-reservation`         | Preferred memory; soft limit                       |
| **CPU limit (quota)**            | `CPUQuota=`                     | `--cpu-quota`, `--cpu-period`  | Limit CPU time available                           |
| **CPU shares (relative weight)** | `CPUShares=`                    | `--cpu-shares`                 | Relative CPU priority                              |
| **CPUs allowed (affinity)**      | `AllowedCPUs=` (cgroup v2)      | `--cpuset-cpus`                | Which CPUs to run on                               |
| **Block IO weight**              | `IOWeight=` or `BlockIOWeight=` | `--blkio-weight`               | Relative disk IO weight                            |
| **PIDs limit**                   | `TasksMax=`                     | `--pids-limit`                 | Max number of processes                            |
| **Cgroup delegation**            | `Delegate=yes`                  | N/A                            | Required for containers to manage their own cgroup |
| **OOMScoreAdjust**               | `OOMScoreAdjust=`               | `--oom-score-adj`              | Adjusts OOM killer preference                      |
| **Swappiness**                   | `MemorySwapMax=` (cgroup v2)    | `--memory-swap`                | Controls swap behavior                             |

| Setting                 | `systemd`                               | `docker`                           | Notes                        |
| ----------------------- | --------------------------------------- | ---------------------------------- | ---------------------------- |
| **Read-only root FS**   | `ReadOnlyPaths=` / `ProtectSystem=full` | `--read-only`                      | Makes FS immutable           |
| **Capability control**  | `CapabilityBoundingSet=`                | `--cap-add`, `--cap-drop`          | Restricts Linux capabilities |
| **User Namespaces**     | `User=` with `DynamicUser=yes`          | `--userns`                         | Isolate UID/GID mappings     |
| **Mount propagation**   | `MountFlags=` or mount units            | `--mount`, `--volume`, `--tmpfs`   | Manage mount visibility      |
| **Device restrictions** | `DeviceAllow=`                          | `--device`, `--device-cgroup-rule` | Limit device access          |

| Feature                   | `systemd`                             | `docker`                | Notes                   |
| ------------------------- | ------------------------------------- | ----------------------- | ----------------------- |
| **Restart policy**        | `Restart=`                            | `--restart`             | Auto-restart on failure |
| **Logging**               | `StandardOutput=journal`              | `--log-driver=journald` | Use journald for logs   |
| **Environment variables** | `Environment=`                        | `--env`                 | Set process environment |
| **Timeouts**              | `TimeoutStartSec=`, `TimeoutStopSec=` | `--stop-timeout`        | Graceful stop time      |
| **Exec command**          | `ExecStart=`                          | `CMD`, `ENTRYPOINT`     | Main process to run     |


| What you control                      | systemd directive                           | Docker flag / Compose key                                | Notes                                                                                       |
| ------------------------------------- | ------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Relative share** (v2) / shares (v1) | `CPUWeight=` (or `CPUShares=` on v1)        | `--cpu-shares`                                           | Higher weight ⇒ more cycles. ([freedesktop.org][1], [docs.docker.com][2])                   |
| **Hard ceiling**                      | `CPUQuota=` + optional `CPUQuotaPeriodSec=` | `--cpu-quota`, `--cpu-period`, or the shorthand `--cpus` | Limits μs of CPU per period (defaults 100 ms). ([freedesktop.org][1], [docs.docker.com][2]) |
| **CPU affinity**                      | `AllowedCPUs=` / `CPUAffinity=`             | `--cpuset-cpus`                                          | Pins to specific cores. ([freedesktop.org][1], [docs.docker.com][2])                        |

[1]: https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html "systemd.resource-control"
[2]: https://docs.docker.com/engine/containers/resource_constraints/ "Resource constraints | Docker Docs"


| What you control           | systemd directive | Docker flag            | Notes                                                                            |
| -------------------------- | ----------------- | ---------------------- | -------------------------------------------------------------------------------- |
| **Hard limit**             | `MemoryMax=`      | `--memory` (`-m`)      | Process killed when limit exceeded. ([freedesktop.org][1], [docs.docker.com][2]) |
| **Soft / high-water mark** | `MemoryHigh=`     | `--memory-reservation` | Reclaim begins when crossed.                                                     |
| **Swap allowance**         | `MemorySwapMax=`  | `--memory-swap`        | Total = RAM + swap.                                                              |

[1]: https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html?utm_source=chatgpt.com "systemd.resource-control - Freedesktop.org"
[2]: https://docs.docker.com/engine/containers/resource_constraints/ "Resource constraints | Docker Docs
"


| systemd     | Docker         | Effect                                                                                          |
| ----------- | -------------- | ----------------------------------------------------------------------------------------------- |
| `TasksMax=` | `--pids-limit` | Caps the number of simultaneous threads/processes. ([freedesktop.org][1], [docs.docker.com][2]) |

[1]: https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html "systemd.resource-control"
[2]: https://docs.docker.com/reference/cli/docker/container/run/?utm_source=chatgpt.com "docker container run - Docker Docs"

| What you control              | systemd                                        | Docker                                                                                 |                                                                        |
| ----------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Relative I/O weight**       | `IOWeight=`                                    | `--blkio-weight`                                                                       | Competes for device time. ([freedesktop.org][1], [docs.docker.com][2]) |
| **Throttle bandwidth / IOPS** | `IOReadBandwidthMax=` / `IOWriteBandwidthMax=` | `--device-read-bps`, `--device-write-bps`, `--device-read-iops`, `--device-write-iops` | Per-device limits.                                                     |

[1]: https://www.freedesktop.org/software/systemd/man/250/systemd.resource-control.html?utm_source=chatgpt.com "systemd.resource-control - Freedesktop.org"
[2]: https://docs.docker.com/reference/cli/docker/container/update/?utm_source=chatgpt.com "docker container update - Docker Docs"


| Purpose            | systemd                                          | Docker                             |
| ------------------ | ------------------------------------------------ | ---------------------------------- |
| Device allow/deny  | `DeviceAllow=`, `DevicePolicy=`                  | `--device`, `--device-cgroup-rule` |
| Linux capabilities | `CapabilityBoundingSet=`, `AmbientCapabilities=` | `--cap-add`, `--cap-drop`          |
| Read-only root FS  | `ProtectSystem=strict` / `ReadOnlyPaths=`        | `--read-only`                      |


| Resource controller     | systemd unit directive                                                        | Docker CLI flag(s)                                                                                                   | Notes                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **CPU shares**          | `CPUAccounting=yes`<br>`CPUShares=` *n*<br>`CPUWeight=` *w*                   | `--cpu-shares` *n*<br>`--cpu-weight` *w* (cgroup v2 only)                                                            | Shares are a relative weight.  In cgroup v2 you’d normally use `CPUWeight` rather than `CPUShares`. |
| **CPU quota**           | `CPUQuota=` *percent*%                                                        | `--cpu-period=100000 --cpu-quota=` *microseconds*                                                                    | e.g. `CPUQuota=50%` ≈ `--cpu-period=100000 --cpu-quota=50000`                                       |
| **CPU affinity**        | `CPUAffinity=` *mask*                                                         | `--cpuset-cpus=` *cpus*                                                                                              | Pin the unit/container to specific CPU cores.                                                       |
| **Memory limit**        | `MemoryAccounting=yes`<br>`MemoryMax=` *bytes*                                | `--memory=` *bytes*<br>`--memory-swap=` *bytes*                                                                      | Systemd also has `MemoryHigh`, `MemoryLow`, `MemoryMin` on cgroup v2.                               |
| **Memory reservation**  | —— (not directly)                                                             | `--memory-reservation=` *bytes*                                                                                      | On cgroup v2 you’d use `MemoryLow=` for a soft-limit.                                               |
| **Swap limit**          | `MemorySwapMax=` *bytes*                                                      | `--memory-swap=` *bytes*                                                                                             | Swap-limit must be ≥ memory limit.                                                                  |
| **Block IO weight**     | `BlockIOWeight=` *w*                                                          | `--blkio-weight=` *w*                                                                                                | Weight from 10 to 1000.                                                                             |
| **Block IO throttle**   | `BlockIODeviceWeight=`<br>`BlockIOReadBandwidth=`<br>`BlockIOWriteBandwidth=` | `--device-read-bps=` *path\:rate*<br>`--device-write-bps=` *path\:rate*<br>`--blkio-weight-device=` *device\:weight* | Per-device throttling.                                                                              |
| **PIDs limit**          | `TasksMax=` *n*<br>`PIDsMax=` *n*                                             | `--pids-limit=` *n*                                                                                                  | `TasksMax` also limits total threads/processes.                                                     |
| **Unified cgroup path** | `Slice=` *name*.slice<br>`Delegate=` *yes/no*                                 | `--cgroup-parent=` *path*                                                                                            | Attach containers or units under a specific cgroup tree.                                            |


Some IO limits (blkio, io.*) may not work reliably across nested cgroups.

Device restrictions (DeviceAllow=) do not apply to the container unless done explicitly in Docker.