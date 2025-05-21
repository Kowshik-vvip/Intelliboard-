from PIL import Image, ImageDraw

def create_image_gen_icon():
    # Create a new image with a white background
    size = 32
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw a simple AI icon
    # Draw a square frame
    frame_color = (74, 144, 226)  # Blue color
    draw.rectangle([4, 4, size-4, size-4], outline=frame_color, width=2)
    
    # Draw AI text
    text_color = (74, 144, 226)  # Blue color
    draw.text((8, 8), "AI", fill=text_color, font=None)
    
    # Save the image
    img.save('icons/image_gen.png')

if __name__ == '__main__':
    import os
    
    # Create icons directory if it doesn't exist
    if not os.path.exists('icons'):
        os.makedirs('icons')
    
    create_image_gen_icon() 