"""
Hawarma TUI - 烹饪游戏自动化 Agent 的文本用户界面

使用 Textual 框架构建的完整仪表板界面，包含：
- 菜单栏
- 配方选择界面
- 配置面板
- 游戏控制界面
- 日志区域
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Log,
    Select,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.selection_list import Selection
from loguru import logger
from textual.worker import Worker, WorkerState

from hawarma.config import load_config, save_config
from hawarma.recipe import Recipe, Station
from hawarma.services.recipe_manager import RecipeManager
from hawarma.device import setup_device
from hawarma.patches import apply_patch
from hawarma.log import setup_logging

# 将 SelectionList 的选中标记从 "X" 改为 "✓"
from textual.widgets._toggle_button import ToggleButton
ToggleButton.BUTTON_INNER = "✓"


class MainMenuScreen(Screen):
    """主菜单屏幕"""

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("r", "recipes", "配方选择"),
        Binding("c", "config", "配置"),
        Binding("g", "game", "开始游戏"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Hawarma - 烹饪游戏自动化 Agent", classes="title"),
            Static("请选择操作：", classes="subtitle"),
            Button("☰ 配方选择", id="recipes", variant="primary"),
            Button("⚙ 配置设置", id="config", variant="default"),
            Button("▶ 开始游戏", id="game", variant="success"),
            Button("✕ 退出", id="quit", variant="error"),
            classes="menu-container",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recipes":
            self.app.push_screen("recipes")
        elif event.button.id == "config":
            self.app.push_screen("config")
        elif event.button.id == "game":
            self.app.push_screen("game")
        elif event.button.id == "quit":
            self.app.exit()

    def action_recipes(self) -> None:
        self.app.push_screen("recipes")

    def action_config(self) -> None:
        self.app.push_screen("config")

    def action_game(self) -> None:
        self.app.push_screen("game")


class RecipeSelectionScreen(Screen):
    """配方选择屏幕（入口层：选择模式 → 过滤菜谱 → 选择策略）"""

    def __init__(self, recipe_manager: RecipeManager):
        super().__init__()
        self.recipe_manager = recipe_manager
        self._all_recipes = recipe_manager.get_all_recipes()

    def compose(self) -> ComposeResult:
        station = self.app.station
        filtered = [r for r in self._all_recipes if r.station == station]

        # 基于当前 station 构建策略选项和默认值
        strategy_options, strategy_values = self._strategy_options_for_station(station)
        current_strategy = self._resolve_strategy_value(strategy_values)

        yield Header()
        yield Container(
            Static("☰ 配方选择", classes="title"),
            Static("1. 选择模式：", classes="subtitle"),
            Select(
                [("gastronome", "gastronome"), ("dessert", "dessert")],
                value=station.value, id="rs-station-select",
            ),
            Static("2. 选择配方（空格多选）：", classes="subtitle"),
            SelectionList[str](
                *[Selection(r.name, r.slug) for r in filtered],
                id="rs-recipe-list",
            ),
            Static("3. 选择策略：", classes="subtitle"),
            Select(
                options=strategy_options,
                value=current_strategy, id="rs-strategy-select",
            ),
            Horizontal(
                Button("确认开始", id="confirm", variant="primary"),
                Button("返回", id="back", variant="default"),
                classes="button-row",
            ),
            classes="recipe-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        """挂载后无需额外初始化（compose 已预填充）"""
        pass

    def _strategy_options_for_station(self, station: Station) -> tuple[list[tuple[str, str]], list[str]]:
        """根据 station 返回可用的策略选项列表"""
        if station == Station.GASTRONOME:
            options = [
                ("default", "default"), ("cpm", "cpm"),
                ("preempt_score", "preempt_score"),
                ("visibility_aware", "visibility_aware"),
                ("cpm_enhanced", "cpm_enhanced"),
            ]
        else:
            options = [("dessert", "dessert")]
        return options, [v for _, v in options]

    def _resolve_strategy_value(self, strategy_values: list[str]) -> str:
        """解析当前策略值，fallback 到 config"""
        current = self.app.game_strategy or self.app.config.strategy
        return current if current in strategy_values else strategy_values[0]

    def _rebuild_recipe_list(self) -> None:
        """根据当前 station 重建菜谱列表"""
        station = self.app.station
        filtered = [r for r in self._all_recipes if r.station == station]
        sl = self.query_one("#rs-recipe-list", SelectionList)
        sl.clear_options()
        for r in filtered:
            sl.add_option(Selection(r.name, r.slug))

    def _rebuild_strategy_options(self) -> None:
        """根据当前 station 重建策略选项"""
        station = self.app.station
        options, values = self._strategy_options_for_station(station)
        current_strategy = self._resolve_strategy_value(values)
        ss = self.query_one("#rs-strategy-select", Select)
        ss.set_options(options)
        ss.value = current_strategy

    def on_select_changed(self, event: Select.Changed) -> None:
        """Station 选择变化时刷新菜谱和策略"""
        if event.value is Select.NULL:
            return
        if event.select.id == "rs-station-select":
            self.app.station = Station(event.value)
            self._rebuild_recipe_list()
            self._rebuild_strategy_options()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            station = self.app.station
            # 保存 station
            self.app.station = station
            # 保存 strategy
            self.app.game_strategy = self.query_one("#rs-strategy-select", Select).value
            # 保存选中的配方
            sl = self.query_one("#rs-recipe-list", SelectionList)
            selected_slugs = sl.selected
            if selected_slugs:
                self.app.selected_recipes = [
                    r for r in self._all_recipes
                    if r.slug in selected_slugs and r.station == station
                ]
                self.app.pop_screen()
        elif event.button.id == "back":
            self.app.pop_screen()


class ConfigScreen(Screen):
    """配置屏幕"""

    def __init__(self, config):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(classes="config-container"):
            yield Static("⚙ 配置设置", classes="title")
            with TabbedContent():
                with TabPane("基本设置", id="basic"):
                    yield Static("基本设置", classes="tab-title")
                    yield Input(value=self.config.image_directory, placeholder="图片目录", id="image-directory")
                    yield Input(value=self.config.log_directory, placeholder="日志目录", id="log-directory")
                    yield Input(value=self.config.recipes_data_path, placeholder="配方数据路径", id="recipes-data-path")
                    yield Input(value=str(self.config.episode_duration), placeholder="游戏时长（秒）", id="episode-duration")
                with TabPane("屏幕设置", id="screen"):
                    yield Static("屏幕设置", classes="tab-title")
                    yield Input(value=f"{self.config.screen.resolution[0]},{self.config.screen.resolution[1]}", placeholder="分辨率（宽,高）", id="resolution")
                    yield Checkbox(value=self.config.screen.save_screenshots, label="保存截图", id="save-screenshots")
                with TabPane("匹配设置", id="matching"):
                    yield Static("匹配设置", classes="tab-title")
                    yield Input(value=self.config.matching.ingredients_strategy[0], placeholder="匹配策略", id="matching-strategy")
                    yield Input(value=str(self.config.matching.ingredients_threshold), placeholder="匹配阈值", id="matching-threshold")
                with TabPane("游戏设置", id="game"):
                    yield Static("游戏设置", classes="tab-title")
                    yield Input(value=str(self.config.game.cooker_retention), placeholder="灶台保留时间", id="cooker-retention")
                    yield Input(value=str(self.config.game.rush_red_threshold), placeholder="Rush红色阈值", id="rush-threshold")
                with TabPane("调试设置", id="debug"):
                    yield Static("调试设置", classes="tab-title")
                    yield Checkbox(value=self.config.debug.save_order_screenshots, label="保存订单截图", id="save-order-screenshots")
                    yield Checkbox(value=self.config.debug.save_assembly_verify_screenshots, label="保存组装验证截图", id="save-assembly-screenshots")
            with Horizontal(classes="button-row"):
                yield Button("保存配置", id="save", variant="primary")
                yield Button("返回", id="back", variant="default")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.save_config()
            self.app.pop_screen()
        elif event.button.id == "back":
            self.app.pop_screen()

    def save_config(self) -> None:
        # 基本设置
        self.config.image_directory = self.query_one("#image-directory", Input).value
        self.config.log_directory = self.query_one("#log-directory", Input).value
        self.config.recipes_data_path = self.query_one("#recipes-data-path", Input).value
        self.config.episode_duration = int(self.query_one("#episode-duration", Input).value)
        
        # 屏幕设置
        resolution = self.query_one("#resolution", Input).value.split(",")
        self.config.screen.resolution = (int(resolution[0]), int(resolution[1]))
        self.config.screen.save_screenshots = self.query_one("#save-screenshots", Checkbox).value
        
        # 匹配设置
        self.config.matching.ingredients_strategy = [self.query_one("#matching-strategy", Input).value]
        self.config.matching.ingredients_threshold = float(self.query_one("#matching-threshold", Input).value)
        
        # 游戏设置
        self.config.game.cooker_retention = float(self.query_one("#cooker-retention", Input).value)
        self.config.game.rush_red_threshold = int(self.query_one("#rush-threshold", Input).value)

        # 调试设置
        self.config.debug.save_order_screenshots = self.query_one("#save-order-screenshots", Checkbox).value
        self.config.debug.save_assembly_verify_screenshots = self.query_one("#save-assembly-screenshots", Checkbox).value
        
        # 保存到YAML文件
        save_config(self.config)


class GameControlScreen(Screen):
    """游戏控制屏幕"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.game_worker = None

    BINDINGS = [
        Binding("escape", "back", "返回"),
        Binding("r", "recipes", "配方"),
        Binding("c", "config", "配置"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("▶ 游戏控制", classes="title"),
            Horizontal(
                Button("▶ 开始游戏", id="start", variant="success"),
                Button("■ 停止游戏", id="stop", variant="error", disabled=True),
                Button("返回", id="back", variant="default"),
                classes="button-row",
            ),
            Log(id="game-log", auto_scroll=True),
            classes="game-container",
        )
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_recipes(self) -> None:
        self.app.push_screen("recipes")

    def action_config(self) -> None:
        self.app.push_screen("config")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.start_game()
        elif event.button.id == "stop":
            self.stop_game()
        elif event.button.id == "back":
            self.app.pop_screen()

    def start_game(self) -> None:
        self.query_one("#start", Button).disabled = True
        self.query_one("#stop", Button).disabled = False

        log = self.query_one("#game-log", Log)
        log.write_line(f"Station: {self.app.station.value}, Strategy: {self.app.game_strategy or self.config.strategy}\n")
        log.write_line("正在连接设备...\n")
        
        try:
            setup_device(self.config.adb_address)
            apply_patch()
            log.write_line("设备连接成功\n")
        except Exception as e:
            log.write_line(f"设备连接失败: {e}\n")
            self.query_one("#start", Button).disabled = False
            self.query_one("#stop", Button).disabled = True
            return
        
        self._tui_sink_id = logger.add(
            lambda msg: log.write_line(f"{msg.record['time'].strftime('%H:%M:%S.%f')[:-3]} | {msg.record['level'].name: <5} | {msg.record['message']}\n"),
            level="INFO",
            format="",
        )
        
        self.run_game()

    @work(exclusive=True, exit_on_error=False)
    async def run_game(self) -> None:
        """运行游戏逻辑"""
        from hawarma.game import Runner
        from hawarma.game.game_env import GameEnv
        from hawarma.game.scanner import Scanner
        from hawarma.game.operator import Operator
        from hawarma.game.verifier import Verifier
        from hawarma.agent.registry import get_strategy
        
        log = self.query_one("#game-log", Log)
        
        try:
            if not self.app.selected_recipes:
                log.write_line("错误：请先选择配方！\n")
                return
            
            recipes = self.app.selected_recipes
            recipes_dict = {r.slug: r for r in recipes}
            strategy_name = self.app.game_strategy or self.config.strategy
            strategy = get_strategy(strategy_name)
            log.write_line(f"使用策略: {strategy_name}\n")
            
            # DI 组装
            station = self.app.station
            operator = Operator(self.config, recipes, station)
            scanner = Scanner(self.config, recipes)
            verifier = Verifier(self.config)
            cooker_names = list(operator.cooker_positions.keys())
            stockpile_slots = 0 if station == Station.DESSERT else len(self.config.screen.stockpile_positions)
            env = GameEnv(
                cooker_names=cooker_names,
                stockpile_slots=stockpile_slots,
                game_duration=self.config.episode_duration,
                recipes=recipes_dict,
                cooker_retention=self.config.game.cooker_retention,
            )
            bridge = Runner(env, operator, scanner, verifier, strategy, recipes_dict)
            
            log.write_line("=" * 40 + "\n")
            log.write_line("游戏运行中... 设备扫描已启动\n")
            log.write_line(f"Recipes: {[r.name for r in recipes]}\n")
            log.write_line(f"Cookers: {cooker_names}\n")
            log.write_line("=" * 40 + "\n")
            
            # 运行游戏
            stats = await bridge.run()
            
            log.write_line("=" * 40 + "\n")
            log.write_line("Game over!\n")
            log.write_line(f"  Time:        {stats['time']:.1f}s\n")
            log.write_line(f"  Orders done: {stats['orders_served']}\n")
            log.write_line(f"  Score:       {stats['total_score']}\n")
            log.write_line(f"  Timed out:   {stats['orders_timeout']}\n")
            log.write_line(f"  Actions:     {stats['actions_taken']}\n")
            log.write_line("=" * 40 + "\n")
            
        except asyncio.CancelledError:
            log.write_line("游戏被用户中止\n")
        except Exception as e:
            log.write_line(f"游戏错误: {e}\n")

    def stop_game(self) -> None:
        if hasattr(self, '_tui_sink_id'):
            logger.remove(self._tui_sink_id)
            del self._tui_sink_id
        
        for worker in self.app.workers:
            if worker.name == "run_game":
                worker.cancel()
                break
        
        self.query_one("#start", Button).disabled = False
        self.query_one("#stop", Button).disabled = True
        
        log = self.query_one("#game-log", Log)
        log.write_line("正在中止游戏...\n")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Worker 状态变化时更新 UI"""
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            if hasattr(self, '_tui_sink_id'):
                logger.remove(self._tui_sink_id)
                del self._tui_sink_id
            self.query_one("#start", Button).disabled = False
            self.query_one("#stop", Button).disabled = True


class HawarmaApp(App):
    """Hawarma TUI 应用"""

    CSS = """
    Screen {
        layout: vertical;
    }

    .title {
        text-align: center;
        text-style: bold;
        margin: 1 0;
    }

    .subtitle {
        text-align: center;
        margin: 1 0;
    }

    .menu-container {
        align: center middle;
        width: 100%;
        height: 100%;
    }

    .recipe-container, .config-container, .game-container {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }

    .button-row {
        align: center middle;
        margin: 1 0;
    }

    #rs-station-select {
        width: 60%;
        max-width: 30;
        min-width: 16;
        margin: 0 0 1 0;
    }

    #rs-recipe-list {
        height: auto;
        max-height: 60%;
        border: solid green;
    }

    #rs-strategy-select {
        width: 60%;
        max-width: 30;
        min-width: 16;
        margin: 0 0 1 0;
    }

    Button {
        margin: 0 1;
    }

    #recipe-list {
        height: 1fr;
        border: solid green;
    }

    Log {
        height: 1fr;
        border: solid blue;
    }
    """

    def __init__(self):
        super().__init__()
        self.theme = "catppuccin-frappe"
        setup_logging(terminal=False, log_name="tui")
        self.config = load_config()
        self.recipe_manager = RecipeManager(recipes_path="data/recipes.json")
        self.selected_recipes: list[Recipe] = []
        self.station: Station = Station.GASTRONOME
        self.game_strategy: str | None = None

    def on_mount(self) -> None:
        # 注册屏幕
        self.install_screen(MainMenuScreen(), name="main")
        self.install_screen(RecipeSelectionScreen(self.recipe_manager), name="recipes")
        self.install_screen(ConfigScreen(self.config), name="config")
        self.install_screen(GameControlScreen(self.config), name="game")
        
        # 显示主菜单
        self.push_screen("main")


def main():
    """TUI 入口点"""
    app = HawarmaApp()
    app.run()


if __name__ == "__main__":
    main()
