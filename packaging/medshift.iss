; ============================================================================
; medshift —— Windows 安装包脚本（Inno Setup 6）
;
; 前提：先在仓库根目录用 PyInstaller 生成 dist\medshift.exe
;         pyinstaller packaging\medshift.spec --noconfirm --clean
;
; 编译：ISCC.exe packaging\medshift.iss
; 产物：dist\medshift-0.1.0-setup.exe
;
; 说明：Inno Setup 需另行安装（非 Python 依赖）：
;         https://jrsoftware.org/isdl.php
;
; 特性：
;   * 装到当前用户目录（{localappdata}\Programs\medshift），无需管理员权限
;   * 开始菜单 / 桌面快捷方式直接启动图形界面（双击即用）
;   * 卸载时询问是否一并删除用户数据目录（%LOCALAPPDATA%\medshift）
; ============================================================================

#define MyAppName "medshift"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "medshift contributors"
#define MyAppURL "https://github.com/your-org/medshift"
#define MyAppExeName "medshift.exe"

[Setup]
AppId={{7C4E1B90-3A62-4D58-9E71-2F0A6B8C5D43}
AppName={#MyAppName} 医技科室排班器
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; 装到当前用户目录，免管理员权限
DefaultDirName={localappdata}\Programs\medshift
DefaultGroupName=medshift
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=medshift-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayName={#MyAppName} 医技科室排班器
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 安装向导图标（若 packaging\medshift.ico 存在则自动启用，见文件末尾 #if）
#if FileExists(AddBackslash(SourcePath) + "medshift.ico")
SetupIconFile=medshift.ico
#endif

[Languages]
; 中文为核心语言文件（随脚本放在 packaging\ChineseSimplified.isl，构建自包含）
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\docs\gui.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
; 快捷方式直接指向 exe：无参数运行时自动打开图形界面
Name: "{group}\medshift 排班器"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\medshift 命令行（帮助）"; Filename: "{cmd}"; Parameters: "/k ""{app}\{#MyAppExeName}"" --help"; WorkingDir: "{userdocs}"
Name: "{group}\卸载 medshift"; Filename: "{uninstallexe}"
Name: "{autodesktop}\medshift 排班器"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即打开 medshift 排班器"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; 用户数据目录位于 {localappdata}\medshift，安装目录之外，卸载程序默认不会碰它。
; 这里不主动删除，避免误删用户排班数据；如需清理，卸载后手动删除该目录即可。
