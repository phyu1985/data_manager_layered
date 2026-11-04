# コーディングルール

このフォルダーの実装・テスト・実行例に適用する、ユーザー指定のルールです。

- メンバ変数は原則として単一アンダースコア付きの非公開属性にする。
- 外部からの参照が必要な場合だけ公開する。参照のみなら読み取り専用propertyを使う。
- 設定用のfrozen dataclassの項目と、業務用Pydanticモデルのフィールドは、利用側が指定する公開項目として扱う。
- 名前は短くても役割が分かるものにする。長くすればよいわけではなく、文脈とスコープに合わせる。
- 辞書化はto_dictなど慣用的な表現を使う。短いループではi / jも使える。長いスコープ・複数の候補がある場面ではmodel_class / dump_options / file_descriptor等で区別する。
- JSON / JSONL、Pythonで一般的な`self`、`load` / `save`、`dumps` / `loads`、pytestのfixture名など、定着した名称は使ってよい。
- docstringは開始の`"""`直後に半角空白を1つ入れる。一行の説明でも閉じる`"""`は次の行に単独で置く。
- 戻り値がNoneの関数・メソッドには、`-> None`を付けない。`__init__`にも付けない。
- 値を返す関数の戻り値注釈は残す。GeneratorやNoReturnの注釈はNoneを返す関数とは区別する。
- メソッド内は、入力確認・準備・変換・入出力など、意味のまとまりの間に空行を入れる。
- 改行は文字数合わせではなく、引数・条件・データ構造のまとまりで判断する。短い宣言や単純な呼出の過剰な折り返しは避ける。
- クラスのdocstringでは、何を実現する役割か、どこまでを担当して他のクラスへ何を委譲するかを説明する。
- メソッドのdocstringは目的・入出力・重要な前提を簡潔に記し、実装手順の長い説明を詰め込まない。
- 処理順や分岐の理由、排他範囲、データ保護、型判別の意図は、該当コードの近くのコメントで説明する。
- 概要はdocstring、処理の段階と判断理由は実装中へ置き、同じ説明を両方へ重複させない。
- 名前から明らかな単純なgetter等を長く説明したり、各行を言い換えるだけのコメントを増やしたりしない。
- 責務が異なる長い処理は、役割が分かる名前のメソッドへ分ける。必要のない共通層は増やさない。

## 検証

変更後は、専用仮想環境のpytestとPyrightで既存の動作・型推論を確認する。
`typecheck/negative.py`と`typecheck/services_negative.py`は誤った入力型の検出用であり、それぞれ3件のreportArgumentTypeが期待結果。
スタイル変更だけのために、実装をなぞるユニットテストは追加しない。

## 設計と可読性

- 単一責任・委譲・DRY・KISSを、保守する人の理解しやすさで判断する。原則のためだけにクラスや汎用基盤を増やさない。
- 処理側へは用途別Presetsを直接渡す。管理用オブジェクトからの多段参照や、項目ごとの転送プロパティで隠さない。
- モデル・版変換・保存・編集ライフサイクル・帳票・外部反映を、それぞれの変更理由に応じて分ける。
- 仕様が違う処理の小さな重複まで機械的に共通化せず、同じ規則の重複を優先して除く。

`typecheck/versioning_negative.py`と`typecheck/analysis_negative.py`は、それぞれ2件のreportArgumentTypeが期待結果。通常のPyright対象には含めず、個別に確認する。

## 配置と依存方向

- 自作パッケージのインストール、src、sys.pathやPYTHONPATHの変更を導入しない。ルートmain.pyまたはpython -mで起動する。
- View→UseCase→DataManager/Domain、DataManager→Domainを許可し、逆方向参照を避ける。レイヤのimportはトップからの絶対パスを使う。
- Domainはファイルを開かない。画面とprintはView、例の表示はexamplesへ置く。
- referenceは過去資料の保管であり、現実装・通常テスト・型チェックの対象にしない。
- requirementsは外部依存だけを管理する。検証はルートREADMEのコマンドを使う。

`typecheck/documents_negative.py`は2件のreportArgumentTypeが期待結果。CSV・JSONLの利用者メタはRowsDocument / load_document / save_documentで扱い、JSONLの型照合メタと混ぜない。

## 今回の合意

- CSVの新規呼出はCsvOptions一つへ揃える。旧3名は移行用の同一型の別名。
- KVの保存文法識別行は出力・要求しない。既存自由コメント・元配置の保存は対象外。
- 解析編集は保存領域の固定管理場所を共有し、失効したセッションの保存・後始末を拒否する。所有者情報を時間経過だけで自動破棄しない。
- 未提示形式は架空例として明示し、実ファイル対応済みと表現しない。
- 今回は新規テストケースを増やさず、既存ケースの仕様変更分と実行例で確認する。実SMB・Linux接続は別途確認事項。

## 名前とI/F

- Repositoryはload(path)/save(path,value)、FileServiceは構成済みパスに対するload()/save(value)/save_as(path,value)とする。読取/書込専用はFileReader/FileWriterを選ぶ。
- 版変換の有無をServiceの呼び方へ漏らさず、Versioned…Repositoryへ委譲する。
- 解析の編集管理はAnalysisWorkspace、加工入力の組立てはUseCase.processing、外部反映はExternalUpdaterとする。
- 旧名は移行用として区別し、現行例・説明へ新旧の流儀を混在させない。

## 計算と反映

- 計算関数は入力Presetsを変更せず、必要な計算結果を返す。UseCaseが結果を明示的に反映し、変更対象を選んで保存する。
- AnalysisWorkspaceは編集権と保存を管理する。解析アルゴリズムを持たせない。
- コアのコメントは、初見・久しぶりの読者が何を作る処理か、どの段階で何を確定するかをつかめるようにする。目的・流れ・判断理由を節目に短く記す。

## YAMLと構造付きブロック

- テンプレートは現在YAMLだけを対象とする。保存先と別の固定ディレクトリから読む。
- 版変換後の出力辞書を正本とし、既存文書やテンプレートから廃止キーを復活させない。metaと本文は一文書としてcastする。
- ブロックの文法はBlockRowsFormat、平坦な対応付けはBlockRowsSerializer、属性行の対応付けはAttributeBlockSerializerへ分ける。

- 可読性調整の説明コメントは主要なコアコードへ置く。examples・testsへ説明コメントを増やさない。
