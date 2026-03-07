#!/usr/bin/env python3
"""
Create a simple icon for PGLOK application.
This generates a basic icon using PIL.
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon():
    # Create a 256x256 image with transparent background
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Background circle (dark theme matching app)
    margin = 20
    draw.ellipse([margin, margin, size-margin, size-margin], 
                fill=(20, 15, 14, 255), outline=(141, 50, 30, 255), width=8)
    
    # Text "PG" in the center
    try:
        # Try to use a nice font
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except:
        # Fallback to default font
        font = ImageFont.load_default()
    
    # Draw "PG" text
    text = "PG"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 20
    
    draw.text((x, y), text, fill=(221, 214, 200, 255), font=font)
    
    # Add "LOK" below
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40) if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") else ImageFont.load_default()
    text_small = "LOK"
    bbox_small = draw.textbbox((0, 0), text_small, font=font_small)
    text_small_width = bbox_small[2] - bbox_small[0]
    
    x_small = (size - text_small_width) // 2
    y_small = y + 80
    
    draw.text((x_small, y_small), text_small, fill=(186, 169, 141, 255), font=font_small)
    
    # Save in multiple formats
    img.save('icon.png', 'PNG')
    img.save('icon.ico', 'ICO')
    img.save('icon.icns', 'ICNS')
    
    print("✅ Icon created successfully!")
    print("   Files created: icon.png, icon.ico, icon.icns")

if __name__ == "__main__":
    create_icon()
