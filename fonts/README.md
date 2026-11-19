# 字体

内置思源黑体 Heavy、站酷小薇体和站酷快乐体。字体文件和对应 SIL OFL 许可一起分发，浏览器预览与视频渲染使用同一文件。

- [思源黑体](https://github.com/adobe-fonts/source-han-sans)
- [站酷小薇体，Google Fonts 源文件](https://github.com/google/fonts/tree/main/ofl/zcoolxiaowei)
- [站酷快乐体，Google Fonts 源文件](https://github.com/google/fonts/tree/main/ofl/zcoolkuaile)

用户上传的 TTF / OTF 字体存放在 `data/fonts/`，不会提交到 Git。文件内容校验后以 SHA-256 标识存放，字体名称从 OpenType name 表读取；删除字体前检查已保存的文字、字幕引用以及正在执行的任务。
