[app]
title = Steam手机令牌验证器
package.name = steamguardauth
package.domain = org.example

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

version = 1.0.0

# 打包进 APK 的 Python 依赖
requirements = python3,kivy==2.3.0,requests,urllib3,certifi,charset-normalizer,idna,plyer

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png

# 权限: 联网 + 读写外部存储(用于选取/保存 .maFile)
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.api = 34
android.minapi = 23
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# 使用 AndroidX (Kivy 2.x 推荐)
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
