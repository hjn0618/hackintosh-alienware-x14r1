# Alienware x14 R1 — macOS Tahoe 26.7.3

OpenCore EFI for Alienware x14 R1 running macOS Tahoe 26.7.3.

这是针对 **macOS 26.7.3（25G342）** 的 `EFI/OC` 配置，使用 Intel AX211、SMBIOS `MacBookPro16,2` 和 OpenCore **1.0.9 DEBUG**（`DBG-109-2026-11-08`）。

## 阶段 2：修复蓝牙

OC 沿用阶段 1 的配置和驱动。蓝牙修复发生在 **macOS 系统卷**，因此这个 commit 新增修复脚本，OC 文件没有变化。

| 组件 | 版本 |
| --- | --- |
| Lilu | 1.7.3 |
| IntelBluetoothFirmware | 2.5.3 |
| IntelBTPatcher | 2.5.3 |
| BlueToolFixup | 2.7.2 |
| AirportItlwm | 2.4.0 |

### 修复方法

BlueToolFixup 的内存补丁与 `bluetoothd` 的 APFS 压缩页面校验发生冲突，引起 `SIGBUS / KERN_MEMORY_ERROR`。本机已用原始字节和补丁字节精确复现内核日志中的两组哈希。

脚本把目标电脑自己的 `/usr/sbin/bluetoothd` 以未压缩形式重新存储，保持原始程序内容、苹果签名和权限，创建未封印启动快照，并保留原快照供回退。**仅复制 OC 不包含此修复。** 本机修复后蓝牙已恢复，其他电脑仍需实测。

需要 Python 3.9+、Intel macOS **25G342**、已关闭 Authenticated Root 与 SIP 文件系统保护，且实际启动 OC 的 `SecureBootModel` 为 `Disabled`。脚本会检查条件，不会自动修改安全设置或重启。先备份重要数据，关闭其他系统更新及补丁工具。

```sh
python3 scripts/bt_uncompress.py check
sudo python3 scripts/bt_uncompress.py apply --yes
# 保存工作、手动重启后验证
sudo python3 scripts/bt_uncompress.py verify
```

回退使用 `sudo python3 scripts/bt_uncompress.py rollback --yes`，再手动重启。回退选择整个修复前的系统卷快照；后续系统构建或快照已经变化、原快照丢失时会拒绝自动回退。脚本不捆绑苹果系统程序或本机 UUID，已有未压缩文件会跳过重复修复。

系统更新或重装后需重新检查。工具只支持已验证的 25G342，不能把旧版系统程序用于新系统。本阶段尚未启用 AirDrop 驱动。

## 使用前

- `PlatformInfo → Generic` 的 `SystemSerialNumber`、`MLB`、`SystemUUID` 已清空，`ROM` 已置零。请为自己的机器生成并填写，不能直接沿用他人的标识。
- 本仓库只包含 `EFI/OC`，不是完整启动盘；现有 EFI 还需匹配的 `EFI/BOOT/BOOTx64.efi`。先备份自己的 EFI，保留其他系统的启动目录。
- ACPI、USB、图形及其他硬件配置针对本机。同型号的不同硬件配置也应单独检查；不将未实测的功能标为正常。

第三方组件版权归各原作者。主要上游：[OpenCore](https://github.com/acidanthera/OpenCorePkg)、[Lilu](https://github.com/acidanthera/Lilu)、[BlueToolFixup](https://github.com/acidanthera/BrcmPatchRAM)、[IntelBluetoothFirmware](https://github.com/lshbluesky/IntelBluetoothFirmware)、[AirportItlwm](https://github.com/laobamac/itlwm)。
