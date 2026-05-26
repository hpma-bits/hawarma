# AGENTS.md

> **涓婁笅鏂囩储寮?*锛氭湰鏂囨。鏄」鐩殑鍏ュ彛绱㈠紩銆傞渶瑕佹繁鍏ヤ簡瑙ｄ换浣曟ā鍧楁椂锛岃鍏堥槄璇诲搴旂殑 `ARCHITECTURE.md` 鏂囦欢鑾峰彇瀹屾暣涓婁笅鏂囥€?

## 馃椇锔?涓婁笅鏂囧湴鍥?

### 椤圭洰姒傝
杩欐槸涓€涓?Python 鐑归オ娓告垙鑷姩鍖栨満鍣ㄤ汉锛屼娇鐢?asyncio 骞跺彂澶勭悊銆丳ydantic 鏁版嵁楠岃瘉鍜?Airtest UI 鑷姩鍖栥€?

| 涓婁笅鏂?| 鏂囦欢 | 浣曟椂闃呰 |
|--------|------|----------|
| **椤圭洰鎬昏** | [`ARCHITECTURE.md`](ARCHITECTURE.md) | 浜嗚В鏁翠綋鐩綍缁撴瀯鍜屾ā鍧楀叧绯?|
| **鏍稿績浠ｇ爜** | [`src/hawarma/ARCHITECTURE.md`](src/hawarma/ARCHITECTURE.md) | 淇敼鏍稿績閫昏緫銆佺悊瑙ｆ暟鎹祦鍜屾灦鏋?|
| **Agent 鍐崇瓥** | [`src/hawarma/agent/ARCHITECTURE.md`](src/hawarma/agent/ARCHITECTURE.md) | 淇敼 Agent 绛栫暐銆佸姩浣滅被鍨嬨€佷紭鍏堢骇 |
| **妗ユ帴灞?* | [`src/hawarma/game/ARCHITECTURE.md`](src/hawarma/game/ARCHITECTURE.md) | 淇敼 UI 鎿嶄綔銆佺姸鎬佽拷韪€佹壂鎻忓櫒銆佸弻寰幆鏋舵瀯 |
| **鏈嶅姟灞?* | [`src/hawarma/services/ARCHITECTURE.md`](src/hawarma/services/ARCHITECTURE.md) | 淇敼閰嶆柟绠＄悊绛夋湇鍔＄粍浠?|
| **宸ュ叿鍑芥暟** | [`src/hawarma/utils/ARCHITECTURE.md`](src/hawarma/utils/ARCHITECTURE.md) | 淇敼鍥惧儚澶勭悊宸ュ叿 |
| **鏂囨。** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 娓告垙瑙勫垯銆丄gent绛栫暐銆佹灦鏋勮璁?|
| **娴嬭瘯** | [`tests/ARCHITECTURE.md`](tests/ARCHITECTURE.md) | 娣诲姞鎴栦慨鏀规祴璇?|
| **瀹為獙** | [`experiments/ARCHITECTURE.md`](experiments/ARCHITECTURE.md) | 杩愯鍩哄噯娴嬭瘯銆佹煡鐪嬪疄楠岃褰?|

### 蹇€熷鑸細鎸変换鍔￠€夋嫨涓婁笅鏂?

| 浠诲姟 | 闃呰椤哄簭 |
|------|----------|
| 淇敼 Agent 绛栫暐 | `docs/game_rules.md` 鈫?`src/hawarma/agent/ARCHITECTURE.md` 鈫?`src/hawarma/ARCHITECTURE.md` |
| 淇敼 UI 鎿嶄綔 | `src/hawarma/game/ARCHITECTURE.md` 鈫?`src/hawarma/ARCHITECTURE.md` |
| 淇敼璁㈠崟妫€娴?| `src/hawarma/game/ARCHITECTURE.md` (scanner) 鈫?`docs/game_rules.md` |
| 娣诲姞鏂版祴璇?| `tests/ARCHITECTURE.md` 鈫?瀵瑰簲妯″潡鐨?ARCHITECTURE.md |
| 杩愯鍩哄噯娴嬭瘯 | `experiments/ARCHITECTURE.md` 鈫?`playground/` 鐩綍 |
| 淇敼閰嶇疆 | `configs/config.yaml` 鈫?`src/hawarma/config.py` |

---

## 鈿狅笍 閲嶈鍘熷垯

### 鏂囨。浼樺厛鍘熷垯

**蹇呴』鎶?`docs/` 浣滀负鐪熷疄淇℃伅婧?*锛?
- 鎵€鏈夋父鎴忚鍒欍€佺畻娉曡璁°€佺瓥鐣ュ垎鏋愰兘浠?`docs/` 涓殑鏂囨。涓哄噯
- 鎬濊€冮棶棰樻椂锛?*浠庢枃妗ｅ嚭鍙?*锛岃€屼笉鏄粠浠ｇ爜鍑哄彂
- 浠ｇ爜瑕佷笌鏂囨。淇濇寔涓€鑷达紝濡傛灉浠ｇ爜涓庢枃妗ｅ啿绐侊紝浠ユ枃妗ｄ负鍑?

**鐪熷疄娓告垙鐩稿叧鏂囨。**锛堜粎淇濈暀杩欎簺锛夛細
- [`docs/game_rules.md`](docs/game_rules.md) - 娓告垙瑙勫垯锛堝敮涓€渚濇嵁锛?
- [`docs/agent_strategy.md`](docs/agent_strategy.md) - Agent绛栫暐鍜屽疄楠岀粨鏋?
- [`docs/real_game_implementation.md`](docs/real_game_implementation.md) - 鐪熷疄娓告垙瀹炵幇

### 妯℃嫙鍣ㄥ眬闄愭€?

- 妯℃嫙鍣ㄥ彲鑳戒笉鑳藉畬鍏ㄥ弽鏄犵湡瀹炴父鎴忕殑琛屼负锛堝骞惰鎬э級
- 閲嶈缁撹闇€瑕佸湪鐪熷疄鐜涓獙璇?
- 涓嶈杩囧害渚濊禆妯℃嫙鍣ㄧ殑娴嬭瘯缁撴灉

### 瀹為獙楠岃瘉

- 閲嶈缁撹闇€瑕佸灞€娴嬭瘯楠岃瘉锛堝缓璁?0灞€浠ヤ笂锛?
- 鑰冭檻涓嶅悓recipes缁勫悎鐨勫樊寮?
- 浠庢枃妗ｄ腑鐨勬父鎴忚鍒欏嚭鍙戝垎鏋愰棶棰?

---

## 馃彈锔?Harness 瀹炶返

### 涓婁笅鏂囧姞杞界瓥鐣?

1. **榛樿鍙姞杞?AGENTS.md**锛氭湰鏂囨。鍖呭惈瓒冲鐨勮鍒欏拰绱㈠紩
2. **鎸夐渶娣卞叆**锛氭牴鎹换鍔＄被鍨嬶紝浠庝笂琛ㄧ殑"蹇€熷鑸?涓€夋嫨瀵瑰簲鐨?ARCHITECTURE.md
3. **閫愬眰灞曞紑**锛氫粠鏍?`ARCHITECTURE.md` 鈫?瀛愮洰褰?`ARCHITECTURE.md` 鈫?鍏蜂綋婧愭枃浠?

### 涓婁笅鏂囧畬鏁存€?

姣忎釜 `ARCHITECTURE.md` 鏂囦欢鍖呭惈锛?
- 鐩綍鐩殑鍜屾枃浠跺垪琛?
- 杈撳叆/杈撳嚭瀹氫箟
- 妯″潡闂村叧绯诲拰鏁版嵁娴?
- 鍏抽敭璁捐鍐崇瓥鍜屽師鐞?

### 缁存姢瑙勫垯

1. 浠讳綍鏋舵瀯鍙樻洿蹇呴』鏇存柊鐩稿叧鐨?`ARCHITECTURE.md`
2. 姣忎釜鐩綍蹇呴』鏈?`ARCHITECTURE.md`
3. 鏂囦欢澶村繀椤诲０鏄庯細`涓€鏃︽枃浠跺唴瀹规湁鏇存柊锛屽姟蹇呭寮€澶存敞閲婅繘琛岀浉搴旂殑蹇呰鏇存柊锛屽悓鏃舵洿鏂版墍灞炵洰褰曠殑md`

---

## 馃敡 甯哥敤鍛戒护

### 杩愯搴旂敤锛堢湡瀹炴父鎴忥級

榛樿浣跨敤 **DefaultStrategy**锛堜富鍔ㄩ鐑归奥 + 鍐崇瓥浼樺厛绾т紭鍖栵級锛?

#### 鍛戒护琛岀晫闈?CLI)
```bash
.venv\Scripts\activate
python -m hawarma
```

#### 鏂囨湰鐢ㄦ埛鐣岄潰 (TUI)
```bash
.venv\Scripts\activate
python -m hawarma.tui
```

TUI 鎻愪緵瀹屾暣鐨勪华琛ㄦ澘鐣岄潰锛屽寘鎷?
- 📋 配方选择界面
- ⚙️ 配置面板（可编辑所有配置）
- 🎮 游戏控制界面（开始、暂停、停止）
- 📊 实时日志显示

#### 鍒囨崲绛栫暐

绛栫暐閫氳繃閰嶇疆鏂囦欢鎴栧懡浠よ鍙傛暟鍒囨崲锛屾棤闇€淇敼浠ｇ爜銆傝瑙?[`docs/agent_strategy.md`](docs/agent_strategy.md)銆?

```bash
# 閰嶇疆鏂囦欢: configs/config.yaml
strategy: "gastronome"      # CPM enhanced cascade (濞寸偠鐫愰敍灞惧春閸? 或 "dessert"

# 鍛戒护琛岃鐩?
python -m hawarma --strategy gastronome
python -m playground bench --games 50 --strategies gastronome,dessert
```

### 杩愯娴嬭瘯
```bash
.venv\Scripts\activate
python -m unittest discover tests        # 鍏ㄩ儴娴嬭瘯
python -m unittest tests.test_capture_speed  # 鍗曚釜鏂囦欢
python -m unittest discover -v tests     # 璇︾粏杈撳嚭
```

### 杩愯妯℃嫙锛圥layground锛?
```bash
.venv\Scripts\activate
python -m playground run --seed 42                    # 杩愯鍗曞眬
python -m playground bench --games 50                 # 杩愯鍩哄噯娴嬭瘯
python -m playground bench --games 100 --csv out.csv  # 瀵煎嚭 CSV
python -m playground replay replay.json               # 鍥炴斁璁板綍
```

### 鐜璁剧疆
```bash
uv pip install -e .
python -m venv .venv
.venv\Scripts\activate
```

---

## 馃摑 浠ｇ爜瑙勮寖

### 绫诲瀷娉ㄨВ
- Python 3.10+ 灏忓啓娉涘瀷锛歚list[str]`銆乣dict[str, int]`
- 浣跨敤 `|` 鑱斿悎杩愮畻绗︼細`Order | None`
- 鎵€鏈夊叕鍏卞嚱鏁?鏂规硶蹇呴』鏈夌被鍨嬫彁绀?

### 鍛藉悕绾﹀畾
- **鍙橀噺/鍑芥暟**锛歚snake_case`
- **绫?*锛歚PascalCase`
- **甯搁噺**锛歚UPPER_SNAKE_CASE`
- **绉佹湁鏂规硶**锛歚_leading_underscore`

### 瀵煎叆椤哄簭
1. 鏍囧噯搴?
2. 绗笁鏂瑰簱
3. 鏈湴瀵煎叆
4. 鐩稿瀵煎叆

### 骞跺彂
- 浣跨敤 `asyncio` 鍜?`asyncio.Lock()`
- 浣跨敤 `asyncio.create_task()` 骞惰窡韪换鍔?
- 浣跨敤 `asyncio.gather()` 鍒嗙粍骞跺彂鎿嶄綔

### 閿欒澶勭悊
- 浣跨敤 `loguru` 缁撴瀯鍖栨棩蹇?
- 鎹曡幏鍏蜂綋寮傚父鑰岄潪瑁?`except:`
- 璁板綍閿欒鍚庡啀 re-raise

### 鍙嶆ā寮?
- 涓嶄娇鐢?`List[Type]` 鈫?鐢?`list[Type]`
- 涓嶄娇鐢?`Optional[Type]` 鈫?鐢?`Type | None`
- 涓嶄娇鐢ㄨ８ `except:` 鈫?鎹曡幏鍏蜂綋寮傚父
- 涓嶉噸澶嶈皟鐢?`asyncio.get_event_loop().time()` 鈫?缂撳瓨缁撴灉
- 涓嶅垱寤烘湭璺熻釜鐨?asyncio 浠诲姟 鈫?浣跨敤浠诲姟璺熻釜闆嗗悎
- 涓嶅鍏?Airtest 绉佹湁鏂规硶 鈫?浣跨敤鍏叡 API

---
## Behavioral guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" 鈫?"Write tests for invalid inputs, then make them pass"
- "Fix the bug" 鈫?"Write a test that reproduces it, then make it pass"
- "Refactor X" 鈫?"Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] 鈫?verify: [check]
2. [Step] 鈫?verify: [check]
3. [Step] 鈫?verify: [check]
```



Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

------

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

