import pygame
import os

pygame.init()

screen = pygame.display.set_mode((800,600))
pygame.display.set_caption("FridgeBud Food Test")

SPRITE_PATH = r"C:\Users\hongy\PixelFood\PixelFood\Split"

sprites = {}

# 加载图片
for file in os.listdir(SPRITE_PATH):

    if file.endswith(".png"):

        name = file.replace(".png","")

        path = os.path.join(SPRITE_PATH,file)

        sprites[name] = pygame.image.load(path)
        

print("Loaded:", sprites.keys())

# 完整食物列表
ALL_FOODS = ['Apple', 'AppleWorm', 'Avocado', 'Bacon', 'Beer', 'Boar', 'Bread', 'Brownie', 'Bug', 'Cheese', 'Cherry', 'Chicken', 'ChickenLeg', 'Cookie', 'DragonFruit', 'Eggplant', 'Eggs', 'Fish', 'FishFillet', 'FishSteak', 'Grub', 'Grubs', 'Honey', 'Honeycomb', 'Jam', 'Jerky', 'Kiwi', 'Marmalade', 'MelonCantaloupe', 'MelonHoneydew', 'MelonWater', 'Moonshine', 'Olive', 'Onion', 'Peach', 'PepperGreen', 'Pepperoni', 'PepperRed', 'Pickle', 'PickledEggs', 'PieApple', 'PieLemon', 'PiePumpkin', 'Pineapple', 'Potato', 'PotatoRed', 'Pretzel', 'Ribs', 'Roll', 'Sake', 'Sardines', 'Sashimi', 'Sausages', 'Shrimp', 'Steak', 'Stein', 'Strawberry', 'Sushi', 'Tart', 'Tomato', 'Turnip', 'Waffles', 'Whiskey', 'Wine']

# 初始食物列表 - 只显示已加载的食物
food_list = [f for f in ["Eggs","Apple","Avocado"] if f in sprites]

# 粉色背景颜色 RGB
PINK = (255, 192, 203)
LIGHT_GRAY = (240, 240, 240)
DARK_GRAY = (100, 100, 100)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (50, 200, 50)
RED = (200, 50, 50)

# 字体设置
font_large = pygame.font.Font(None, 36)
font_small = pygame.font.Font(None, 24)
input_text = ""
running = True
input_active = True
suggestions = []

while running:

    screen.fill(PINK)  # 背景改成粉色

    # 显示输入提示
    if input_active:
        # 生成建议列表
        if input_text:
            suggestions = [f for f in ALL_FOODS if f.lower().startswith(input_text.lower()) and f in sprites][:5]
        else:
            suggestions = []
        
        prompt = font_large.render("搜索食物:", True, BLACK)
        screen.blit(prompt, (50, 30))
        
        input_display = font_large.render(input_text if input_text else "输入食物名称...", True, DARK_GRAY if not input_text else BLACK)
        input_box = pygame.Rect(50, 80, 500, 50)
        pygame.draw.rect(screen, WHITE, input_box)
        pygame.draw.rect(screen, BLACK, input_box, 3)
        screen.blit(input_display, (70, 95))
        
        # 显示建议
        if suggestions:
            suggestion_text = " | ".join(suggestions)
            sugg_display = font_small.render(f"建议: {suggestion_text}", True, GREEN)
            screen.blit(sugg_display, (50, 145))
        
        hint = font_small.render("按 ENTER 添加  |  按 ESC 跳过  |  按 ↑↓ 选择建议", True, DARK_GRAY)
        screen.blit(hint, (50, 180))
        
        # 显示当前已添加的食物数
        count_text = font_small.render(f"已添加: {len(food_list)} 个食物", True, BLACK)
        screen.blit(count_text, (50, 210))

    # 显示食物列表网格
    x = 50
    y = 300
    col = 0
    max_cols = 8

    for food in food_list:

        if food in sprites:

            sprite = pygame.transform.scale(sprites[food], (64, 64))

            screen.blit(sprite, (x, y))
            
            # 显示食物名称
            name_text = font_small.render(food[:8], True, BLACK)
            screen.blit(name_text, (x, y + 70))

            x += 90
            col += 1
            if col >= max_cols:
                col = 0
                x = 50
                y += 110

    pygame.display.update()

    for event in pygame.event.get():

        if event.type == pygame.QUIT:
            running = False
        
        # 处理用户输入
        if input_active:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    if input_text and input_text in sprites:
                        if input_text not in food_list:
                            food_list.append(input_text)
                            print(f"✓ 已添加: {input_text}")
                        else:
                            print(f"⚠ {input_text} 已在列表中")
                        input_text = ""
                    elif input_text:
                        print(f"✗ 找不到: {input_text}")
                elif event.key == pygame.K_ESCAPE:
                    input_active = False
                    print("跳过输入")
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                else:
                    # 只接受字母输入
                    if event.unicode.isalpha():
                        input_text += event.unicode

pygame.quit()
exit()