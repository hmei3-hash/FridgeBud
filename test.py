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

food_list = ["Eggs","Apple","Avocado"]

# 粉色背景颜色 RGB
PINK = (255, 192, 203)

# 字体设置
font = pygame.font.Font(None, 36)
input_text = ""
running = True
input_active = True

while running:

    screen.fill(PINK)  # 背景改成粉色

    # 显示输入提示
    if input_active:
        prompt = font.render("请输入食物名称 (输入后按 ENTER):", True, (0, 0, 0))
        screen.blit(prompt, (50, 50))
        
        input_display = font.render(input_text, True, (0, 0, 0))
        input_box = pygame.Rect(50, 100, 300, 40)
        pygame.draw.rect(screen, (255, 255, 255), input_box)
        pygame.draw.rect(screen, (0, 0, 0), input_box, 2)
        screen.blit(input_display, (60, 110))

    # 显示食物列表
    x = 100

    for food in food_list:

        if food in sprites:

            sprite = pygame.transform.scale(sprites[food],(64,64))

            screen.blit(sprite,(x,250))

            x += 80

    pygame.display.update()

    for event in pygame.event.get():

        if event.type == pygame.QUIT:
            running = False
        
        # 处理用户输入
        if input_active:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    if input_text:
                        print(f"用户输入: {input_text}")
                        if input_text in sprites:
                            food_list.append(input_text)
                            print(f"已添加 {input_text} 到食物列表")
                        else:
                            print(f"警告: {input_text} 未找到")
                        input_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                else:
                    input_text += event.unicode

pygame.quit()
exit()