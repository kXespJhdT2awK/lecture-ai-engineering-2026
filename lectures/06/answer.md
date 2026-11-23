# 第6回 解答

## 演習

Codespaces ではなく手元の Mac（Python 3.13.7、pydantic-ai 2.57.0）で実行しました。モデルは講座の既定の gemini-3.5-flash-lite です。どの STEP でも 503・429 は出ず、各コマンドは1回で通りました。出力は [logs/](logs/) に残しています。

- STEP 1 のツールの名前：glossary_search_glossary

`app.agent --list-tools` では `search_materials` が1個、`app.mcp_agent --list-tools` では `[server] glossary: コマンドで起動（uv run python -m app.mcp_server）` のあとに `glossary_search_glossary` が1個表示されました。どちらも名前・説明文・引数の3つが同じ形で並んでいます。ログは [step1_agent_list_tools.txt](logs/step1_agent_list_tools.txt)、[step1_mcp_list_tools.txt](logs/step1_mcp_list_tools.txt) です。

- STEP 2 の [tool call]：

```text
[tool call]   glossary_search_glossary({'query': '3レベル'})
```

`[tool return]` には用語集の「宿題の3レベル」（第1回）の定義が返り、`[usage]` は入力 709 tokens、出力 144 tokens、モデル応答 2 回でした。ログは [step2_trace.txt](logs/step2_trace.txt) です。

- STEP 3 の [tool call]：

```text
[tool call]   fetch_fetch({'url': 'https://modelcontextprotocol.io/'})
```

`--list-tools` で `[server] fetch: コマンドで起動（uvx mcp-server-fetch==2026.11.11 --no-readability-js）` が出て、ツールが `fetch_fetch` を足した2個になりました。初回は uvx が46個のパッケージを入れ、6.5 秒かかりました。質問の `[usage]` は入力 2,173 tokens、出力 108 tokens、モデル応答 2 回です。ログは [step3_list_tools.txt](logs/step3_list_tools.txt)、[step3_trace.txt](logs/step3_trace.txt) です。

- STEP 4 の [tool call]：

```text
[tool call]   aws_aws___search_documentation({'search_phrase': 'Amazon S3 バージョニング とは'})
[tool call]   aws_aws___search_documentation({'topics': ['general'], 'search_phrase': 'Using versioning in S3 buckets'})
```

`--list-tools` で `[server] aws: URL に接続（https://knowledge-mcp.global.api.aws）` が出て、`aws_aws___read_documentation`、`aws_aws___search_documentation`、`aws_aws___list_regions`、`aws_aws___get_regional_availability`、`aws_aws___retrieve_skill` の5個が増え、計7個になりました。質問では検索を2回呼び、`[usage]` は入力 11,272 tokens、出力 132 tokens、モデル応答 3 回でした。ログは [step4_list_tools.txt](logs/step4_list_tools.txt)、[step4_trace.txt](logs/step4_trace.txt) です。

- 気づき・疑問：

STEP 3 の実行ログには、fetch サーバーが先に `https://modelcontextprotocol.io/robots.txt` を取得し、307 のリダイレクトを追って `/docs/2026-07-28/getting-started/intro.md` を取得し直したことが出ていました。補足の表にある「robots.txt で禁止されていないかを確かめる」という既定の動作が、実際の通信として見えました。

STEP 4 の1回目の検索は日本語の検索語で、返った上位は `querying-aws-s3` というスキルの説明でした。モデルは2回目に英語の検索語「Using versioning in S3 buckets」と `topics: ['general']` を自分で付けて検索し直し、「What is Amazon S3?」の S3 Versioning の節を取得してから答えました。このため応答が3回になり、入力トークンは STEP 2 の約 16 倍になりました。検索語の言語を変えたのはモデルの判断で、指示文には書いていません。

AWS のツール名は `aws_aws___search_documentation` のように `aws` が2回付き、アンダースコアが3つ続きます。サーバー側のツール名がもともと `aws___search_documentation` で、そこに演習のエージェントが「サーバー名_」を付けるためです。

## 宿題

- 取り組んだレベル：発展

- やったこと：

自分が普段使っている Claude Code を選び、MCP サーバーの設定方法を公式ドキュメントで調べました。調べた日付は 2026-11-23 です。参照したのは次の3ページです。

1. Connect Claude Code to tools via MCP：https://code.claude.com/docs/en/mcp
2. CLI reference：https://code.claude.com/docs/en/cli-reference
3. Environment variables：https://code.claude.com/docs/en/env-vars

あわせて、手元の Claude Code 2.1.292 で `claude mcp --help` と `claude mcp add --help` の表示を確かめ、自分のユーザー設定ファイル（.claude.json）の形を、中身の値を出さずにキーだけ読みました。そのうえで、演習の `app/mcp_servers.json` を Claude Code にそのまま読ませる実験を2通り行いました。

- 結果：

調べた4項目は次の通りです。

| 調べること | Claude Code（公式ドキュメント、2026-11-23） | 演習の app/mcp_servers.json |
|---|---|---|
| 設定を書く場所 | 基本は `claude mcp add` で登録し、コマンドが設定ファイルに書き込む。ファイルはスコープによって `~/.claude.json`（local と user）か、プロジェクトのルートの `.mcp.json`（project）。JSON をそのまま渡す `claude mcp add-json <name> '<json>'` と、起動時に渡す `--mcp-config` もある | リポジトリの `app/mcp_servers.json` 1つ。`app/mcp_agent.py` がこのパスを固定で読む |
| コマンドで起動する書き方 | `claude mcp add [options] <name> -- <command> [args...]`。`--` より後ろはそのままサーバーの起動コマンドに渡る。JSON では `"command"`、`"args"`、`"env"` で、`"type": "stdio"` を書くか、`type` を省く（`type` のない項目は stdio として読む） | `"command"` と `"args"` |
| URL で接続する書き方 | `claude mcp add --transport http <name> <url>`。JSON では `"type": "http"` と `"url"` が必要で、`streamable-http` も `http` の別名として通る。ほかに `sse`（非推奨）と `ws` がある。認証は `--header` や `"headers"`、OAuth | `"url"` だけで、`type` は書かない |
| 有効になる範囲 | local（既定。今のプロジェクトだけで、自分だけ。`~/.claude.json` の中のそのプロジェクトのパスの下に入る）、project（今のプロジェクトだけで、`.mcp.json` をバージョン管理に入れてチームと共有）、user（自分のすべてのプロジェクト。`~/.claude.json`）の3つ。同じ名前が複数のスコープにあれば local、project、user の順で優先し、項目どうしは混ぜない | このリポジトリで `app.mcp_agent` を動かしたときだけ |

手元の設定ファイルでは、ユーザースコープのサーバー7個がトップレベルの `mcpServers` に入っていて、コマンドで起動するものは `type`・`command`・`args`・`env`、URL のものは `type`・`url` のキーを持ち、どれも `type`（`stdio` か `http`）が書かれていました。`projects` の下の local スコープのサーバーは0個でした。手元では環境変数 `CLAUDE_CONFIG_DIR` で設定ディレクトリを変えているので、使われていたファイルは `~/.claude.json` ではなく、その設定ディレクトリの直下の `.claude.json` でした。この置き場所の変わり方は、読んだ3ページには書かれておらず、ファイルの中身と `claude mcp list` の表示が一致することから確かめました。

次に、演習の設定ファイルを Claude Code がそのまま読めるかを試しました。

1つ目は、STEP 4 の状態の `app/mcp_servers.json` を `.mcp.json` という名前で空のディレクトリにコピーし、`claude mcp list` を実行しました。`glossary` と `fetch` は `⏸ Pending approval (run claude to approve)` と表示され、`aws` は一覧に出ず、診断に Skipped（読み飛ばし）として `MCP server "aws" has a "url" but no "type"; add "type": "http" (or "sse" / "ws") to this entry` と出ました。ログは [claude_mcp_list_mcpjson.txt](logs/homework/claude_mcp_list_mcpjson.txt) です。

2つ目は、リポジトリのルートで `claude -p --strict-mcp-config --mcp-config app/mcp_servers.json --output-format stream-json` を実行し、起動時の情報（system/init）を見ました。`glossary` と `fetch` は connected になり、ツールは `mcp__glossary__search_glossary` と `mcp__fetch__fetch` の2個でした。`aws` は `url_missing_type` というエラーで読み飛ばされました。`aws` に `"type": "http"` を1行足したファイル（[mcp_servers_typed.json](logs/homework/mcp_servers_typed.json)）で同じことをすると、3つとも connected になり、AWS の5個を含む7個のツールが読み込まれました。ログは [claude_p_mcp_config_init.json](logs/homework/claude_p_mcp_config_init.json) です。モデルには「OKとだけ返して」とだけ頼み、MCP のツールは呼ばせていません。

最後に、`"type": "http"` を足したファイルを演習の `app/mcp_agent.py` に読ませると、これまでと同じ7個のツールが表示されました（[mcp_agent_typed_list_tools.txt](logs/homework/mcp_agent_typed_list_tools.txt)）。演習のエージェントは `"command"` か `"url"` があるかだけを見て、`type` は読まないからです。リポジトリの `app/mcp_servers.json` は課題文の通りの形のまま変えていません。

演習の設定と比べた違いは次の5つです。

1. URL の書き方：演習は `"url"` だけで接続しますが、Claude Code は `type` のない項目を stdio として読むので、`"type": "http"` がないと読み飛ばします。実験でもその通りになりました。コマンドで起動する2つは、そのままの形で読めました。
2. 書き込み方：演習はファイルを手で編集しますが、Claude Code は `claude mcp add` などのコマンドで登録するのが基本で、コマンドがスコープに応じたファイルに書き込みます。
3. 有効になる範囲：演習の設定は1つの場所だけですが、Claude Code には local、project、user の3つのスコープがあり、同じ名前のサーバーは優先順位の高いほうだけが使われます。
4. 安全のための承認：`.mcp.json`（project スコープ）のサーバーは、対話の画面で承認するまで使われません（実験の Pending approval）。ドキュメントには、`claude -p` ではこの承認を出せないので確認なしで読み込む、とも書かれています。演習のエージェントは設定に書いたものを確認なしで起動します。
5. ツール名：演習は `glossary_search_glossary` のように「サーバー名_ツール名」ですが、Claude Code は `mcp__glossary__search_glossary` のように `mcp__` を前に付け、サーバー名とツール名の間をアンダースコア2つにしていました。

- 気づき・疑問：

演習のファイルは、課題文の通り Claude Desktop や Cursor と同じ `mcpServers` の形をしているので、そのまま他のソフトウェアでも使えると思っていました。実際には、コマンドで起動するサーバーは Claude Code でもそのまま読めた一方、URL のサーバーは `type` が1行ないだけで読み飛ばされました。Claude Code のドキュメントにも「他のクライアント向けに書かれた `mcpServers` の JSON は、`url` があって `type` がない項目を直してから使う」という節があり、同じ形に見えても、ソフトウェアによって必須の項目が違うことが分かりました。

`claude -p` で `.mcp.json` のサーバーが確認なしで読み込まれるという点は、補足にあった「信頼できるサーバーか」の確認を、承認の画面に頼れない場面があるということだと思いました。clone してきたリポジトリの `.mcp.json` に知らないサーバーが書かれていても、`claude -p` で動かせばそのまま起動されることになります。この点は、ドキュメントで読んだだけで、自分では試していません。

うまくいかなかったこととして、手元には Claude Code が2つ入っていて、PATH で先に見つかる `/opt/homebrew/bin/claude` は 2.1.84、普段使っている `~/.local/bin/claude` は 2.1.292 でした。2.1.84 の `claude mcp --help` では `add-json` の説明が「stdio or SSE」になっていて、ドキュメントの内容（`http` や `ws` も書ける）と合いませんでした。実験はすべて 2.1.292 で行いました。Codex CLI など他のソフトウェアとの比較はしていません。
