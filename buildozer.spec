[app]
title = Steam手机令牌验证器
package.name = steamguardauth
package.domain = org.example

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

version = 1.0.0

# 打包进 APK 的 Python 依赖
# - python3 显式锁定为 3.11.9: 避免 p4a 默认拉取过新的 CPython (如 3.14),
#   因为较新 Python 版本会导致: (1) remote_debugging.c 里 preadv/pwritev 在
#   低于 API24 的 Android 上编译报错; (2) kivy/pyjnius 等包尚未声明支持该
#   Python 版本, 导致 pip 依赖解析显示 "no versions"。
# - hostpython3 必须与 python3 版本一致 (p4a 强制校验), 否则报错:
#   "python3 should have same version as hostpython3, X != Y"
# - kivy 锁定 2.3.1 (而非 2.3.0): 2.3.0 与 Cython 3.x 生成的 OpenGL 绑定代码
#   不兼容, 会报 "too few arguments to function call" 编译错误; 2.3.1 修复了此问题。
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,requests,urllib3,certifi,charset-normalizer,idna,plyer

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png

# 权限: 联网 + 读写外部存储(用于选取/保存 .maFile)
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.api = 34
# minapi 锁定为 24 (Android 7.0): CPython 3.13+ 的 remote_debugging.c 用到
# preadv/pwritev, 这两个函数在 Android Bionic libc 里从 API 24 起才提供声明,
# 低于 24 会导致 "implicit declaration of function 'preadv'" 编译报错。
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# 锁定 build-tools 版本, 避免每次都去抓最新版导致与 API/NDK 组合不匹配
android.build_tools = 34.0.0

# 自动接受 Android SDK 各组件许可证 (build-tools 等首次下载时需要),
# 避免因许可证未确认导致 aidl 等工具找不到。
android.accept_sdk_license = True

# 使用 AndroidX (Kivy 2.x 推荐)
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
