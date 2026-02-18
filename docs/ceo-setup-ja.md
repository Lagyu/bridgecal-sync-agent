# かんたん予定確認・同期（BridgeCal）CEO向けセットアップ手順（日本語）

この手順は、初回セットアップを最短で完了するためのガイドです。

## 事前に準備しておくもの

- Windows PC（Outlook クラシック版がインストール・設定済み）
- かんたん予定確認・同期 配布ZIP（このフォルダ）
- Google OAuth クライアントシークレット JSON

## 1. ZIPを展開する

任意のフォルダに ZIP を展開してください。

## 2. GUI を起動する

展開したフォルダで PowerShell を開き、次を実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-bridgecal-gui.ps1
```

このスクリプトは必要な依存関係を自動で準備し、GUIを起動します。

## 3. はじめてセットアップ

GUI 起動後、`0. はじめてセットアップ` を押してください。

入力する内容:

- Google カレンダーID
- Google クライアントシークレット JSON ファイル
- 自動同期の間隔（通常は `120` 秒）

セットアップ完了後、自動で接続チェック（doctor）が実行されます。

## 4. 手動同期

`2. 今すぐ同期` を押すと、1回同期を実行できます。
同期進捗バーで処理状況を確認できます。

## 5. 自動同期の有効化（任意）

`3. 自動同期をON（管理者権限）` を押すと、ログオン時の自動同期タスクを設定できます。

## 補足

- 設定ファイルの保存先: `%APPDATA%\BridgeCal\config.toml`
- ログの保存先: `%APPDATA%\BridgeCal\bridgecal.log`
- 状態DBの保存先: `%APPDATA%\BridgeCal\state.db`
