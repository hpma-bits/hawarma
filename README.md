# Project Overview

This project is a bot for a cooking game, designed to automate the process of cooking and serving dishes. It uses the `airtest` framework to interact with an Android emulator running the game. The bot is capable of detecting customer orders, managing a cooking pipeline, and strategically stockpiling ingredients to improve efficiency.

## Main Technologies

*   **Python:** The core programming language.
*   **Airtest:** A framework for UI automation of games and apps.
*   **Loguru:** A library for pleasant and powerful logging.
*   **Pydantic:** A library for data validation and settings management.
*   **Questionary:** A library for building interactive command-line prompts.

## Architecture

The application is structured into several key components:

*   **`main.py`:** The entry point of the application. It handles the initial setup, user input for recipe selection, and the main application loop.
*   **`hawarma/app.py`:** The core application class, `CookingBotApp`. It orchestrates the entire cooking process, from detecting orders to managing the cooking pipeline.
*   **`hawarma/services/detection_service.py`:** This service is responsible for detecting customer orders from the screen. It uses image recognition to identify recipes, rush orders, and condiment preferences.
*   **`hawarma/services/cooking_service.py`:** This service handles the physical actions of cooking, stockpiling, and serving in the game. It translates recipes into swipe actions and manages cooker contention.
*   **`hawarma/models.py`:** Defines the data models for the application, such as `Recipe` and `Order`.
*   **`configs/config.yaml`:** The main configuration file for the application. It contains settings for screen coordinates, matching parameters, and other application-level configurations.
*   **`data/recipes.json`:** A JSON file containing the definitions of all the recipes that the bot can cook.

# Building and Running

## Prerequisites

*   Python 3.10 or higher
*   An Android emulator with the game installed. The emulator must be connected to `adb` at `127.0.0.1:16384`.

## Installation

1.  Install the project dependencies using `uv`:
    ```bash
    uv pip install -r requirements.txt
    ```

## Running the Application

1.  Run the `main.py` script:
    ```bash
    python main.py
    ```
2.  The application will prompt you to select the recipes to use for the current session.
3.  After selecting the recipes, the bot will start running and will automatically detect and process orders.

# Development Conventions

## Code Style

The project follows the PEP 8 style guide for Python code.

## Logging

The project uses the `loguru` library for logging. The log level can be configured in `main.py`.

## Configuration

The application's configuration is managed through the `configs/config.yaml` file. This file contains all the screen coordinates and other parameters that the bot needs to function.

## Adding New Recipes

To add a new recipe, you need to:

1.  Add the recipe's definition to the `data/recipes.json` file.
2.  Add the corresponding ingredient and cooker images to the `static/img` directory.

## Must Do

1. 任何功能、写法、架构的更新必须在工作结束后更新相关目录的子文档
2. 每个显式目录中都要有一个极简的架构说明md，内部包括每个文件的名字、地位、功能。文件开头声名：一旦我所属的目录有变化，请更新我
3. 每个模块的开头要有注释，表明模块的输入输出和在系统中的地位，并声名：一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
4. 保证开发过程中项目的分形结构


