# HAWARMA AUTO

This is a python script for the gastronomy game in Harry Potter: Magic Awakened. The core idea is to use TemplateMatching to determine the dishes to be cooked and use virtual input to replace the tedious manual work.

## 环境准备：
airtest的javacap截图需要用旧版本Yosemite.apk替代现有版本才能支持mumu12模拟器。（详见 https://github.com/AirtestProject/Airtest/issues/1085）

## 核心思路：
1.每道菜谱的食材可以分为待加工(raw ingredients)和调味品(condiments)两种，recipes.json定义了目前支持的菜谱。每个菜谱的第一个待加工食材都是独有的(unique)，且游戏中订单的待加工食材的图标位置相对整个订单位置是固定的，因此很适合用待加工食材图标作为模板匹配(TemplateMatch)的目标进而确定该订单对应的菜谱，这就是detect_recipe()方法的功能。

2.确定了订单的菜谱后，利用detect_condiments()方法确定该菜谱的调味偏好(condiments_preferences)，这个方法的核心也是利用模板匹配确定调味品图标和双倍图标是否存在。

3.根据recipe和调味偏好实例化Order对象并加入队列，在合适的时候调用Order.process()方法处理订单。

4.在Order类中，process()方法会依次执行订单处理逻辑。