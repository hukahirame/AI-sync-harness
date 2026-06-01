' AI Chat Auto-Saver — 非表示起動ランチャー
'
' 同じフォルダにある run_server.bat を、画面に表示せずに起動します。
' このファイルへのショートカットを「スタートアップ」フォルダに置くことで、
' Windowsサインイン時に自動でサーバーが起動します。

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' このVBSファイル自身があるフォルダを取得
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
BatPath = ScriptDir & "\run_server.bat"

' run_server.bat を起動
'   第2引数 0 = ウィンドウ非表示
'   第3引数 False = 終了を待たない(バックグラウンド)
WshShell.Run Chr(34) & BatPath & Chr(34), 0, False
