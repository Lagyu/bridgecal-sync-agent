# BridgeCal Sync Agent

[English README](README.md)

BridgeCal は、2 つのカレンダーを同期する **単一ユーザー向け**・**ローカル実行** の同期エージェントです。

- Microsoft Outlook デスクトップ カレンダー（A 社、Windows、Graph/EWS 不可）
- Google カレンダー（B 社）

エージェントは A 社 PC の電源が入っている間だけ動作します。

## クイックスタート（開発）

```bash
uv sync
uv run bridgecal doctor
uv run bridgecal sync --once
```

## Windows へのデプロイ

BridgeCal の実行には以下が必要です。
- Outlook デスクトップがそのマシンで設定済みであること（COM アクセス）
- OAuth **Desktop app** 用の Google OAuth クライアントシークレット JSON
- Python 3.12 以上

Google API キーは不要です。

### ワンコマンドデプロイ（PowerShell）

リポジトリのルートで実行してください。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-bridgecal.ps1
```

このスクリプトで実行される内容:
- Python 3.12+ がなければ `winget` でインストール
- `uv` がなければ `winget` でインストール（失敗時は公式インストーラにフォールバック）
- `uv sync` を実行
- `%APPDATA%\BridgeCal\config.toml` を作成
- Google カレンダー ID を対話で入力
- Google OAuth クライアントシークレットを対話で入力（ファイルパスまたは JSON 貼り付け）
- `uv run bridgecal doctor` を実行
- 任意で `uv run bridgecal sync --once` を初回実行
- 任意でログオン時起動のタスクスケジューラを作成

注意: Outlook はこのスクリプトではインストールされません。Outlook デスクトップは事前にインストール・設定が必要です。

オプション:

```powershell
.\scripts\deploy-bridgecal.ps1 -IntervalSeconds 120 -SkipScheduledTask
```

### デーモン起動用スクリプト

必要に応じて直接実行できます（タスクスケジューラの Action 用）。

```powershell
.\scripts\run-bridgecal-daemon.ps1 -IntervalSeconds 120 -ConfigPath "$env:APPDATA\BridgeCal\config.toml"
```

ドキュメント:
- `docs/index.md`
