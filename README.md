# Live English Captions
![Uploading image.png…]()

Local bilingual captions and English vocabulary learning for Windows.

**当前版本：1.2.0** · [升级记录](CHANGELOG.md)

1.2.0 将中文翻译升级为 NLLB 离线模型，并把字幕模式改为 Windows 原生半透明置顶窗口。旧版升级时先停止记录，运行 `powershell -ExecutionPolicy Bypass -File .\setup.ps1` 下载新模型，再启动服务。`retranslate_history.py` 可备份并修复旧版历史翻译。

## 安装和启动

支持 Windows 10/11 64 位。下载或克隆本项目到本地后，双击 `start.cmd`。首次启动自动安装项目独立的 Python 3.12、依赖和离线模型；需要联网并预留数 GB 磁盘空间。安装结束后浏览器打开 <http://127.0.0.1:8765>。

运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\create-shortcut.ps1` 可创建桌面启动快捷方式。移动项目目录后重新运行该脚本即可更新快捷方式。

## 功能

并行捕获耳机播放音频和麦克风，用 faster-whisper `small.en` 识别英语，由 NLLB-200 600M 离线翻译简体中文，并用 CAM++ 声纹模型区分耳机中的多人。网页仅监听 `127.0.0.1:8765`，无需 API Key。首次安装联网下载 Python、依赖与模型；正常使用不上传音频。语音优先使用 NVIDIA GPU FP16，翻译使用 GPU INT8/FP16；模型初始化或推理失败时独立回退 CPU INT8，并重试当前任务。网页和悬浮窗标题显示各自的 GPU/CPU 模式；CAM++ 保持轻量 CPU 推理。

## 使用

1. 双击 `start.cmd`。首次会安装环境和模型，可能需要较长时间。若模型下载中断，运行 `powershell -ExecutionPolicy Bypass -File .\setup.ps1` 重试。
2. 选择聊天软件正在使用的耳机和麦克风，点击「开始翻译」。默认使用 Windows 输入；若默认为立体声混音，则优先选择当前耳机对应的真实麦克风。也可以选择「不记录麦克风」。麦克风与耳机分别采集、识别并显示，双方同时发言也不会把两路音频拼在一起；麦克风实际拾取的背景声音仍可能影响识别。
3. 实时英文位于上方，中文位于下方独立固定高度区域，时间和人物放在英文同一行；补译不挤动英文。新英文预览优先追加到段落末尾，定稿时在原位保留，确认人物不同后才另分段。GPU 下约每 1 秒提交一次音频快照，CPU 回退时约每 1.8 秒；连续两次识别一致的前文逐步锁定，最近约 6 个词保持可校准。最终英文识别完成即保存和显示，中文异步补齐。预览不写入历史或导出，人物最终由声纹模型标注。相邻同人物、间隔不超过 12 秒且合并后不太长的短句会在页面合成一块；原始记录和导出仍保留每句话。界面通过长轮询等待变更通知，只修改新增或变更文字，空闲时每 15 秒心跳。滚到底部自动跟随，上翻时暂停跟随并保留当前位置，点击跟随状态也能回到最新字幕。跟随时保留最近 12 块，回看和选词期间不移除旧块。
   「字幕模式」打开 Windows 原生半透明置顶悬浮窗，独立于浏览器显示双语字幕。拖动顶部移动窗口，拖动右下角调整尺寸，顶部滑块调整透明度；支持向上回看、跟随最新、停止记录和关闭。关闭悬浮窗仅关闭字幕显示，停止记录需点击「停止记录」。浏览器继续用于设备设置、历史和单词本。
4. 自动标注「我（麦克风）」「对方 1」「对方 2」等。点击人物名称可为同一声纹在本次会话的全部句子命名；「改人物」仅修改当前句。
5. 选中一段英文后点击「翻译选中内容」，再点击「保存到单词本」。单词本保留原句，支持搜索、导出和复习卡片，可以标记「已记住」「还需学习」。
6. 在「按日期回看」查看旧聊天。可以导出某一天，也可点击「导出全部对话（含人物）」一次导出所有已保存记录。导出含北京时间、会话编号、人物、英文、中文，不受实时区 12 段的限制。
7. 「停止」立即结束捕获并处理、保存剩余英文队列；中文任务继续在后台补齐。服务独立在后台运行，关闭启动窗口或网页不会停止捕获；结束聊天时请点击「停止」。强制关机可能丢失尚未识别的音频。已保存但尚未翻译的英文在下次开始记录时恢复中文翻译。

模型下载慢时，可运行 `powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Mirror`，从 `hf-mirror.com` 下载语音模型。语音和翻译模型均支持镜像选项。安装程序检测到 `nvidia-smi` 时尝试安装项目内的 CUDA 12 cuBLAS、NVRTC 和 cuDNN 9 运行库（约 1.3 GB 下载）；安装失败也能使用 CPU。已有环境可运行 `.tools\uv.exe pip install --python .venv\Scripts\python.exe -r requirements-gpu.txt` 补装，无需安装完整 CUDA Toolkit。

## 行为与限制

- 支持英语 → 简体中文。small.en 比旧版 base.en 更大，推理也更慢；口音、术语、音乐与噪声会影响准确率。
- 中文等待完整短句或语义片段；同人物碎片最多额外等待 1.8 秒再合并翻译。最近两段相关英文及已确认中文作为有限上下文，只提取当前片段译文；上下文异常时回退单段翻译。跨会话不复用上下文，已有历史不重译。多条英文共用一段中文时，实时区只显示一次，导出标明关联字幕并保留每条英文、人物和时间。
- 同一个输出设备上的所有声音都会被捕获，包括其他网页、提示音和游戏。建议聊天时暂停其他音频。
- RMS 音量门限用于划分语音，Whisper VAD 进一步过滤静音。音量过小可能漏句，连续发言每 7 秒切段，边界处可能拆开单词。
- 实际延迟取决于推理设备、音质和负载。实时预览是滚动片段重识别，后续词语可能修正句尾；最终分段仍等待约 0.6 秒静音或最长 7 秒。预览任务按音频来源合并，只保留最新快照，最终识别任务优先处理。最终队列最多保留 64 段，积压满时停止捕获并显示错误，避免静默丢弃旧音频。导出覆盖全部已识别、保存的文字；不能保证声音过小、重叠发言等情况下每个词都被识别。
- 蓝牙耳机可能在通话时切换输出设备。停止服务、刷新设备，选择通话正在使用的设备后重新开始。
- 历史和单词本自动保存到 `data/subtitles.sqlite3`，按北京时间日期分组。备份整个 `data` 目录即可保留记录。原始录音不保存，声纹特征仅在当前监听会话的内存中存在。
- 人物编号在每次点击「开始翻译」后重新分配，导出包含会话编号以避免混淆。未知的短句标为「对方（待确认）」。声纹属于近似判断：短句、变声器、噪声、同音色和同时说话会误分；可人工命名或逐句修正。它不会自动知道真实姓名，也无法分离同时重叠的声音。
- 主页面用于设备、历史和单词本管理；「字幕模式」打开独立桌面置顶悬浮窗。

## 开发与验证

### 代码结构

| 文件 | 职责 |
| --- | --- |
| `app.py` | 本机 HTTP 服务、并行音频采集、识别翻译、设备管理和接口 |
| `storage.py` | SQLite 历史记录、单词本、人物名称和全量导出 |
| `translation.py` | 固定英语到简体中文、NLLB 推理与异常字符防护 |
| `speech.py` / `streaming.py` | small.en 模型 revision、稳定前缀与可校准句尾 |
| `caption_layout.py` / `native_view.py` | 共享段落身份、英文原位追加及原生双区增量显示 |
| `inference.py` / `requirements-gpu.txt` | 项目内 CUDA DLL 注册、GPU 优先、模型级 CPU 回退及可选运行库版本 |
| `version.py` / `requirements.lock` | 应用版本和固定依赖 |
| `retranslate_history.py` | 备份数据库并重译旧版历史 |
| `speakers.py` | 声纹特征提取、会话内人物匹配和词级时间对齐 |
| `index.html` / `style.css` / `app.js` | 字幕、历史、查词、复习及滚动跟随界面 |
| `download_models.py` | 下载语音、翻译和声纹模型 |
| `setup.ps1` / `launch.ps1` / `start.cmd` | 安装独立环境和启动后台服务 |
| `create-shortcut.ps1` | 创建或更新桌面快捷方式 |
| `overlay.py` / `overlay_launcher.py` | 原生 Tk 半透明置顶字幕窗及本机兼容启动接口（8767 端口） |
| `tests/` | 单元测试及 Microsoft Edge 浏览器验证 |

个人数据 `data/`、模型 `models/`、虚拟环境 `.venv/` 和工具缓存 `.tools/` 均被 Git 排除。仓库仅保存代码和文档。

浏览器测试的可选依赖在 `requirements-dev.txt`，可运行 `.tools\uv.exe pip install --python .venv\Scripts\python.exe -r requirements-dev.txt` 安装。`tests/browser_check.py` 测试使用独立临时数据库；`tests/layout_check.py` 使用模拟字幕检查当前服务的排版和滚动行为。

`setup.ps1` 使用项目内的 uv 和 Python 虚拟环境，依赖按 `requirements.lock` 固定，依赖默认从华为 PyPI 镜像安装，语音模型支持 Hugging Face 中国镜像选项。small.en 语音模型约 483 MB，声纹模型约 28 MB，翻译模型约 600 MB，另外有运行库。已有安装通过 `start.cmd` 检查并补下载新语音模型。

运行 `.venv\Scripts\python.exe -m unittest discover -s tests -v` 检查队列收尾、服务状态、持久化、分页、声纹聚类和人物导出。浏览器检查位于 `tests/browser_check.py`，需要额外安装 `playwright` 和本机 Microsoft Edge；测试使用临时数据库，不会混入个人记录。已验证英文合成语音识别/翻译、两种合成声音重复匹配，以及这台电脑的耳机和麦克风并行打开。真实多人通话的准确率仍取决于音质和说话方式。

本项目参考了 [echo-sub 的设计](https://github.com/mPhpMaster/echo-sub)，在此独立实现本机网页、持久化记录与个人单词本。

上游说明：[PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[NLLB](https://huggingface.co/facebook/nllb-200-distilled-600M)、[sherpa-onnx 声纹识别](https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html)。

## 翻译质量与模型许可

实时字幕每次新增的英文和中文会以文字颜色和柔和底色突出约 4.5 秒；不改变字重、字号、边框或间距，高亮取消时文字位置和换行保持一致。短句合并时只突出新补充的部分。网页和原生悬浮窗均支持。悬浮窗点击「跟随最新」后持续跟随，向上滚动回看时暂停，滚回底部自动恢复；选择文字时暂缓自动滚动。

悬浮窗中选择英文单词或短语会打开独立翻译窗口，点击「单独翻译」获取中文释义，然后可点击「保存到生词本」。保存内容与网页个人单词本共用本地数据库，并保留原句；只有点击保存才写入。

Whisper `small.en` 使用 CTranslate2 GPU `float16` 推理；NLLB-200 600M 使用 `int8_float16`，失败时分别回退 `int8` CPU。英文通过滚动快照重识别、两次一致的前缀确认和短句尾修正提供预览，在完整片段识别后定稿；中文只翻译最终文本，并使用有限上下文和已确认译文前缀提取当前译文。此实现不属于模型原生逐词流式识别，也不承诺固定延迟。稳定前缀只保护读过的文字，不能保证已确认词语绝对正确；长段落仍需自然换行，最终人物分段可能移动新出现的句尾。

可选真实模型验证：`.venv\Scripts\python.exe tests\realtime_model_check.py`，需要 `.tools/sample.wav` 英文 PCM WAV 测试样本。脚本使用临时数据库，比较预热后的 CPU/GPU 识别耗时，并按正常语速模拟采集，验证英文预览和中文延后补齐；不会播放音频或写入个人记录。

1.2.0 使用 NLLB-200 600M 的 INT8 转换版本，明确指定英语到简体中文。异常私用字符、替换字符和非预期文字会触发重试；仍异常时显示明确提示并保留英文。中文语义正确性不能仅靠字符检查保证，字幕请结合英文判断。

NLLB 权重采用 CC-BY-NC-4.0 许可，仅适用于许可允许的用途；代码仓库不附带模型权重。参见官方模型页。

真实模型回归：`.venv\Scripts\python.exe tests\translation_model_check.py`。历史重译：先停止记录，运行 `.venv\Scripts\python.exe retranslate_history.py`；原数据库备份保存在 `data/backups/`。
