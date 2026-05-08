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
from hawarma.recipe import Recipe
from hawarma.services.recipe_manager import RecipeManager
from hawarma.device import setup_device
from hawarma.patches import apply_patch
from hawarma.log import setup_logging


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
            Static("🎮 Hawarma - 烹饪游戏自动化 Agent", classes="title"),
            Static("请选择操作：", classes="subtitle"),
            Button("📋 配方选择", id="recipes", variant="primary"),
            Button("⚙️ 配置设置", id="config", variant="default"),
            Button("▶️ 开始游戏", id="game", variant="success"),
            Button("❌ 退出", id="quit", variant="error"),
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
    """配方选择屏幕"""

    def __init__(self, recipe_manager: RecipeManager):
        super().__init__()
        self.recipe_manager = recipe_manager

    def compose(self) -> ComposeResult:
        all_recipes = self.recipe_manager.get_all_recipes()
        yield Header()
        yield Container(
            Static("📋 配方选择", classes="title"),
            Static("选择要使用的配方（空格多选）：", classes="subtitle"),
            SelectionList[str](
                *[Selection(recipe.name, recipe.slug) for recipe in all_recipes],
                id="recipe-list",
            ),
            Horizontal(
                Button("确认选择", id="confirm", variant="primary"),
                Button("返回", id="back", variant="default"),
                classes="button-row",
            ),
            classes="recipe-container",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            selection_list = self.query_one("#recipe-list", SelectionList)
            selected_slugs = selection_list.selected
            if selected_slugs:
                all_recipes = self.recipe_manager.get_all_recipes()
                self.app.selected_recipes = [
                    r for r in all_recipes if r.slug in selected_slugs
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
            yield Static("⚙️ 配置设置", classes="title")
            with TabbedContent():
                with TabPane("基本设置", id="basic"):
                    yield Static("基本设置", classes="tab-title")
                    yield Input(value=self.config.image_directory, placeholder="图片目录", id="image-directory")
                    yield Input(value=self.config.log_directory, placeholder="日志目录", id="log-directory")
                    yield Input(value=self.config.recipes_data_path, placeholder="配方数据路径", id="recipes-data-path")
                    yield Input(value=str(self.config.episode_duration), placeholder="游戏时长（秒）", id="episode-duration")
                    yield Input(value=",".join(self.config.cookers), placeholder="灶台类型（逗号分隔）", id="cookers")
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
                    yield Select([("default", "default"), ("cpm", "cpm"), ("preempt_score", "preempt_score"), ("visibility_aware", "visibility_aware")], value=self.config.strategy, id="strategy-select")
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
        """保存配置到文件"""
        # 基本设置
        self.config.image_directory = self.query_one("#image-directory", Input).value
        self.config.log_directory = self.query_one("#log-directory", Input).value
        self.config.recipes_data_path = self.query_one("#recipes-data-path", Input).value
        self.config.episode_duration = int(self.query_one("#episode-duration", Input).value)
        self.config.cookers = tuple(self.query_one("#cookers", Input).value.split(","))
        
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
        self.config.strategy = self.query_one("#strategy-select", Select).value
        
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
            Static("🎮 游戏控制", classes="title"),
            Horizontal(
                Button("▶️ 开始游戏", id="start", variant="success"),
                Button("⏹️ 停止游戏", id="stop", variant="error", disabled=True),
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
        from hawarma.agent.registry import get_strategy
        
        log = self.query_one("#game-log", Log)
        
        try:
            # 检查是否有选中的配方
            if not self.app.selected_recipes:
                log.write_line("错误：请先选择配方！\n")
                return
            
            # 获取策略
            strategy = get_strategy(self.config.strategy)
            log.write_line(f"使用策略: {self.config.strategy}\n")
            
            # 创建桥接器（直接注入 strategy）
            bridge = Runner(self.config, self.app.selected_recipes, strategy)
            
            log.write_line("=" * 40 + "\n")
            log.write_line("游戏运行中... 设备扫描已启动\n")
            log.write_line(f"Recipes: {[r.name for r in self.app.selected_recipes]}\n")
            log.write_line(f"Cookers: {list(self.config.cookers)}\n")
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
        height: 100%;
    }

    .button-row {
        align: center middle;
        margin: 1 0;
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
        setup_logging(terminal=False, log_name="tui")
        self.config = load_config()
        self.recipe_manager = RecipeManager(recipes_path="data/recipes.json")
        self.selected_recipes: list[Recipe] = []

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
