[app]
title = Steam手机令牌验证器
package.name = steamguardauth
package.domain = org.example

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

version = 1.0.0

# 依赖版本说明:
# - kivy 锁定 2.3.1 (而非 2.3.0): 2.3.0 与较新 Cython 生成的 OpenGL 绑定代码
#   不兼容, 会报 "too few arguments to function call" 编译错误。
# - python3/hostpython3 不再手动锁定精确小版本号: 交给 buildozer-action 内置的
#   已验证组合处理, 避免因锁定的补丁版本与 p4a 补丁不匹配导致 grp 模块等
#   编译失败 (Android 没有 Unix 用户组数据库, 需要 p4a 补丁禁用 grp 模块,
#   该补丁按具体小版本号编写, 版本号锁太细容易对不上)。
requirements = python3,kivy==2.3.1,requests,urllib3,certifi,charset-normalizer,idna,plyer

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
android.archs = arm64-v8a,armeabi-v7a

# 自动接受 Android SDK 各组件许可证
android.accept_sdk_license = True

# 使用 AndroidX (Kivy 2.x 推荐)
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
