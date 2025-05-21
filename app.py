from tkinter import *
from tkinter import ttk
import tkinter as tk
from tkinter import filedialog, colorchooser, messagebox
import os
import sys
from tkinter import simpledialog
from PyPDF2 import PdfReader
from doubt_db import ScreenAnalyzer
from chatbot import TutorChatBot
from PIL import Image, ImageTk, ImageGrab
import io
import json
from datetime import datetime
import requests
from io import BytesIO
import time
from huggingface_hub import InferenceClient




root = Tk()
root.title("Smart White Board")
# Make window fullscreen by default
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
root.geometry(f"{screen_width}x{screen_height}+0+0")
root.config(bg="#ffffff")
root.resizable(True, True)


def resource_path(relative_path):
    """ Get the absolute path to the resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


# Calculate canvas size based on screen dimensions
canvas_width = int(screen_width * 0.9)  # 80% of screen width
canvas_height = int(screen_height * 0.9)  # 80% of screen height

# Calculate positions for UI elements
sidebar_width = 60
toolbar_height = 50
canvas_x = sidebar_width + 20
canvas_y = 10

current_x = 0
current_y = 0
start_x = None
start_y = None
color = "black"
active_tool = None

# Create main Canvas first
canvas = Canvas(root, width=canvas_width, height=canvas_height, background="white", cursor="hand2")
canvas.place(x=canvas_x, y=canvas_y)

# Create status bar early
status_bar = Label(root, text="Ready", bd=1, relief=SUNKEN, anchor=W)
status_bar.pack(side=BOTTOM, fill=X)

# Variables for functionality 
screen_capture = None

# Undo/Redo history
history = []
redo_stack = []
current_state = 0
max_history = 50

# Zoom and Pan variables
zoom_factor = 1.0
pan_x = 0
pan_y = 0
panning = False
last_x = 0
last_y = 0

# Drawing modes and settings
line_width = 2
fill_shapes = False
text_font = "Arial"
text_size = 12
brush_style = "solid"  # solid, dashed, dotted

# Session management
session_name = "Untitled Session"
session_modified = False
autosave_interval = 5 * 60 * 1000  # 5 minutes in milliseconds

def save_canvas_state():
    """Save current canvas state to history"""
    global history, current_state, redo_stack, session_modified

    if len(history) > 0 and current_state < len(history) - 1:
        # If we're not at the end of history, truncate history
        history = history[:current_state + 1]
        redo_stack = []

    try:
        # Get canvas position
        x = root.winfo_rootx() + canvas.winfo_x()
        y = root.winfo_rooty() + canvas.winfo_y()
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        
        # Capture the canvas area directly
        img = ImageGrab.grab(bbox=(x, y, x+width, y+height))
        
        # Convert to bytes
        with io.BytesIO() as bytes_io:
            img.save(bytes_io, format='PNG')
            bytes_data = bytes_io.getvalue()
        
        history.append(bytes_data)
        current_state = len(history) - 1
        
        # Limit history size
        if len(history) > max_history:
            history.pop(0)
            current_state -= 1
        
        session_modified = True
        update_ui_state()
    except Exception as e:
        # If screenshot fails, just keep going without saving state
        print(f"Could not save canvas state: {e}")
        # Don't update session_modified or history in case of failure

def restore_canvas_state(state_data):
    """Restore canvas state from stored data"""
    try:
        canvas.delete('all')
        
        # Convert bytes to image 
        with io.BytesIO(state_data) as bytes_io:
            img = Image.open(bytes_io)
            photo_img = ImageTk.PhotoImage(img)
            
            # We need to keep a reference to avoid garbage collection
            canvas.photo_img = photo_img
            canvas.create_image(0, 0, image=photo_img, anchor=NW)
    except Exception as e:
        print(f"Could not restore canvas state: {e}")
        # If restore fails, at least clear the canvas
        canvas.delete('all')

def undo():
    """Undo last action"""
    global current_state, redo_stack
    
    if current_state > 0:
        # Save current state to redo stack
        redo_stack.append(history[current_state])
        
        # Go back one state
        current_state -= 1
        restore_canvas_state(history[current_state])
        update_ui_state()

def redo():
    """Redo previously undone action"""
    global current_state, redo_stack
    
    if redo_stack:
        # Get state from redo stack
        state_data = redo_stack.pop()
        
        # Move forward in history
        current_state += 1
        if current_state >= len(history):
            history.append(state_data)
        else:
            history[current_state] = state_data
            
        restore_canvas_state(state_data)
        update_ui_state()

def update_ui_state():
    """Update UI elements based on current state"""
    # Update undo/redo buttons state if defined
    try:
        if 'undo_button' in globals():
            undo_button.config(state=NORMAL if current_state > 0 else DISABLED)
        if 'redo_button' in globals():
            redo_button.config(state=NORMAL if redo_stack else DISABLED)
    except (NameError, TclError):
        # Buttons might not be defined yet
        pass
    
    # Update session name to show modified status
    if session_modified:
        root.title(f"Smart White Board - {session_name}*")
    else:
        root.title(f"Smart White Board - {session_name}")

def addline(event):
    global current_x, current_y, pan_x, pan_y, last_x, last_y, panning
    if active_tool is None:
        # Apply zoom and pan transformations
        canvas_x = (event.x - pan_x) / zoom_factor
        canvas_y = (event.y - pan_y) / zoom_factor
        
        # Create line with appropriate dash pattern based on brush style
        dash_pattern = ()  # solid
        if brush_style == "dashed":
            dash_pattern = (5, 2)
        elif brush_style == "dotted":
            dash_pattern = (2, 2)
            
        canvas.create_line((current_x, current_y, canvas_x, canvas_y), 
                          width=int(slider.get()),
                          fill=color, 
                          capstyle=ROUND, 
                          smooth=True,
                          dash=dash_pattern)
        current_x, current_y = canvas_x, canvas_y
    elif active_tool == "pan" and panning:
        # Handle panning
        delta_x = event.x - last_x
        delta_y = event.y - last_y
        pan_x += delta_x
        pan_y += delta_y
        last_x, last_y = event.x, event.y
        canvas.scan_dragto(event.x, event.y, gain=1)

def handle_release(event):
    global panning, active_tool
    # If we were drawing shapes, finish the shape
    if active_tool in ["rectangle", "oval", "triangle", "square"]:
        add_shape(event)
    # If we were drawing or just finished a shape, save canvas state
    elif active_tool is None and event.num == 1:
        save_canvas_state()
    
    # If we were panning, stop panning
    if event.num == 2:  # Middle button
        panning = False
        save_canvas_state()  # Save state after panning

def insertimage():
    global filename, f_img
    filename = filedialog.askopenfilename(initialdir=os.getcwd(), title="select image file",
                                        filetypes=[("Image files", "*.jpg *.jpeg *.png"), ("All file","new.txt")])
    if not filename:
        return
        
    try:
        # Use PIL for better image handling
        pil_img = Image.open(filename)
        f_img = ImageTk.PhotoImage(pil_img)
        
        # Center the image on the canvas
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        img_width = f_img.width()
        img_height = f_img.height()
        center_x = (canvas_width - img_width) // 2
        center_y = (canvas_height - img_height) // 2
        my_img = canvas.create_image(center_x, center_y, image=f_img)
        root.bind("<B3-Motion>", my_callback)
        
        # Save state after inserting image
        save_canvas_state()
    except Exception as e:
        messagebox.showerror("Error", f"Could not load image: {str(e)}")

def my_callback(event):
    global f_img, filename
    # Apply zoom and pan transformations
    canvas_x = (event.x - pan_x) / zoom_factor
    canvas_y = (event.y - pan_y) / zoom_factor
    
    # Use PIL for better image handling
    pil_img = Image.open(filename)
    f_img = ImageTk.PhotoImage(pil_img)
    my_img = canvas.create_image(canvas_x, canvas_y, image=f_img)

def add_shape(event):
    global start_x, start_y, active_tool
    if active_tool == "rectangle":
        # Apply zoom and pan transformations
        canvas_x = (event.x - pan_x) / zoom_factor
        canvas_y = (event.y - pan_y) / zoom_factor
        
        if fill_shapes:
            canvas.create_rectangle(start_x, start_y, canvas_x, canvas_y,
                                  outline=color, width=int(slider.get()),
                                  fill=color)
        else:
            canvas.create_rectangle(start_x, start_y, canvas_x, canvas_y,
                                  outline=color, width=int(slider.get()))
    elif active_tool == "square":
        # Apply zoom and pan transformations
        canvas_x = (event.x - pan_x) / zoom_factor
        canvas_y = (event.y - pan_y) / zoom_factor
        
        # Calculate size based on the largest dimension
        size = max(abs(canvas_x - start_x), abs(canvas_y - start_y))
        if canvas_x >= start_x:
            end_x = start_x + size
        else:
            end_x = start_x - size
            
        if canvas_y >= start_y:
            end_y = start_y + size
        else:
            end_y = start_y - size
            
        if fill_shapes:
            canvas.create_rectangle(start_x, start_y, end_x, end_y,
                                  outline=color, width=int(slider.get()),
                                  fill=color)
        else:
            canvas.create_rectangle(start_x, start_y, end_x, end_y,
                                  outline=color, width=int(slider.get()))
    elif active_tool == "oval":
        # Apply zoom and pan transformations
        canvas_x = (event.x - pan_x) / zoom_factor
        canvas_y = (event.y - pan_y) / zoom_factor
        
        if fill_shapes:
            canvas.create_oval(start_x, start_y, canvas_x, canvas_y,
                             outline=color, width=int(slider.get()),
                             fill=color)
        else:
            canvas.create_oval(start_x, start_y, canvas_x, canvas_y,
                             outline=color, width=int(slider.get()))
    elif active_tool == "triangle":
        # Apply zoom and pan transformations
        canvas_x = (event.x - pan_x) / zoom_factor
        canvas_y = (event.y - pan_y) / zoom_factor
        
        # Calculate the third point of the triangle
        mid_x = start_x + (canvas_x - start_x) / 2
        
        if fill_shapes:
            canvas.create_polygon(start_x, canvas_y, mid_x, start_y, canvas_x, canvas_y,
                                outline=color, width=int(slider.get()),
                                fill=color)
        else:
            canvas.create_polygon(start_x, canvas_y, mid_x, start_y, canvas_x, canvas_y,
                                outline=color, width=int(slider.get()))
    
    active_tool = None

def show_color(new_color):
    global color
    color = new_color

def choose_color():
    global color
    color_code = colorchooser.askcolor(title="Choose Color")
    if color_code[1]:  # If color was selected (not canceled)
        color = color_code[1]
        color_indicator.config(bg=color)
        safe_update_status(f"Selected color: {color}")

def new_canvas():
    canvas.delete('all')
    display_pallete()
    save_canvas_state()

def set_eraser():
    global color, active_tool
    active_tool = None
    color = "white"

def set_rectangle_tool():
    global active_tool
    active_tool = "rectangle"

def set_oval_tool():
    global active_tool
    active_tool = "oval"

def set_triangle_tool():
    global active_tool
    active_tool = "triangle"

def set_square_tool():
    global active_tool
    active_tool = "square"

def set_text_tool():
    global active_tool
    active_tool = "text"

def set_line_style(style):
    global brush_style
    brush_style = style

def set_fill(fill):
    global fill_shapes
    fill_shapes = fill

def toggle_fill():
    global fill_shapes
    fill_shapes = not fill_shapes
    fill_button.config(text="Fill: On" if fill_shapes else "Fill: Off")

def safe_update_status(message):
    """Safely update status bar text"""
    try:
        if 'status_bar' in globals():
            status_bar.config(text=message)
    except (NameError, TclError):
        print(f"Status message: {message}")

def zoom_in():
    global zoom_factor
    zoom_factor *= 1.2
    canvas.scale("all", 0, 0, 1.2, 1.2)
    safe_update_status(f"Zoom: {int(zoom_factor * 100)}%")

def zoom_out():
    global zoom_factor
    zoom_factor /= 1.2
    canvas.scale("all", 0, 0, 1/1.2, 1/1.2)
    safe_update_status(f"Zoom: {int(zoom_factor * 100)}%")

def reset_zoom():
    global zoom_factor, pan_x, pan_y
    # Reset to original size
    canvas.scale("all", 0, 0, 1/zoom_factor, 1/zoom_factor)
    zoom_factor = 1.0
    pan_x = 0
    pan_y = 0
    safe_update_status("Zoom: 100%")

def save_session():
    global session_name, session_modified
    file_path = filedialog.asksaveasfilename(
        defaultextension=".iwb",
        filetypes=[("Interactive Whiteboard", "*.iwb"), ("All Files", "*.*")],
        title="Save Session",
        initialfile=session_name if session_name != "Untitled Session" else "")
    
    if not file_path:
        return
    
    try:
        # Get canvas position
        x = root.winfo_rootx() + canvas.winfo_x()
        y = root.winfo_rooty() + canvas.winfo_y()
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        
        # Capture the canvas area directly
        img = ImageGrab.grab(bbox=(x, y, x+width, y+height))
        
        # Save canvas to PNG format
        img_path = os.path.splitext(file_path)[0] + ".png"
        img.save(img_path, "PNG")
        
        # Save session info (slides, history, etc.)
        session_data = {
            "name": os.path.basename(file_path),
            "slides": slides,
            "current_slide": current_slide,
            "timestamp": datetime.now().isoformat(),
        }
        
        with open(file_path, "w") as f:
            json.dump(session_data, f)
        
        session_name = os.path.basename(file_path)
        session_modified = False
        update_ui_state()
        safe_update_status(f"Saved session as {session_name}")
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save session: {e}")
        print(f"Save failed: {e}")

def load_session():
    global session_name, slides, current_slide, session_modified
    file_path = filedialog.askopenfilename(
        defaultextension=".iwb",
        filetypes=[("Interactive Whiteboard", "*.iwb"), ("All Files", "*.*")],
        title="Load Session")
    
    if not file_path:
        return
    
    try:
        # Load session data
        with open(file_path, "r") as f:
            session_data = json.load(f)
        
        # Load information
        session_name = session_data.get("name", os.path.basename(file_path))
        slides = session_data.get("slides", [])
        current_slide = session_data.get("current_slide", 0)
        
        # Load canvas image
        img_path = os.path.splitext(file_path)[0] + ".png"
        if os.path.exists(img_path):
            img = Image.open(img_path)
            photo_img = ImageTk.PhotoImage(img)
            canvas.delete('all')
            canvas.photo_img = photo_img
            canvas.create_image(0, 0, image=photo_img, anchor=NW)
        
        session_modified = False
        update_ui_state()
        
        if slides:
            display_slide()
    except Exception as e:
        messagebox.showerror("Error", f"Could not load session: {str(e)}")

def autosave():
    if session_modified:
        try:
            # Only autosave if there are changes
            temp_dir = os.path.join(os.path.expanduser("~"), ".smart_whiteboard")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Get canvas position
            x = root.winfo_rootx() + canvas.winfo_x()
            y = root.winfo_rooty() + canvas.winfo_y()
            width = canvas.winfo_width()
            height = canvas.winfo_height()
            
            # Capture the canvas area directly
            img = ImageGrab.grab(bbox=(x, y, x+width, y+height))
            
            # Save to temp file
            autosave_path = os.path.join(temp_dir, "autosave.png")
            img.save(autosave_path)
            
            # Save session info
            session_data = {
                "name": session_name,
                "slides": slides,
                "current_slide": current_slide,
                "timestamp": datetime.now().isoformat(),
            }
            
            with open(os.path.join(temp_dir, "autosave.iwb"), "w") as f:
                json.dump(session_data, f)
            
            safe_update_status(f"Autosaved at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"Autosave failed: {e}")
    
    # Schedule next autosave
    root.after(autosave_interval, autosave)

def export_canvas():
    """Export canvas to various formats"""
    file_path = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[
            ("PNG Image", "*.png"),
            ("JPEG Image", "*.jpg"),
            ("PDF Document", "*.pdf"),
        ],
        title="Export Canvas")
    
    if not file_path:
        return
    
    try:
        # Get canvas position
        x = root.winfo_rootx() + canvas.winfo_x()
        y = root.winfo_rooty() + canvas.winfo_y()
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        
        # Capture the canvas area directly
        img = ImageGrab.grab(bbox=(x, y, x+width, y+height))
        
        # Determine format based on extension
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.pdf':
            # For PDF, create a PDF with the image
            img.save(file_path, "PDF", resolution=100.0)
        else:
            # For other formats, use direct save
            img.save(file_path)
            
        safe_update_status(f"Exported to {os.path.basename(file_path)}")
    except Exception as e:
        messagebox.showerror("Export Error", f"Could not export canvas: {e}")
        print(f"Export failed: {e}")

def display_pallete():
    colors_list = ["#2c3e50", "#34495e", "#e74c3c", "#f39c12", "#27ae60", "#2980b9", "#8e44ad"]
    for i, color_name in enumerate(colors_list):
        id = colors.create_rectangle((10, 10 + i * 30, 30, 30 + i * 30), fill=color_name)
        colors.tag_bind(id, '<Button-1>', lambda x, col=color_name: show_color(col))

color_box = PhotoImage(file=resource_path("icons/color_section.png"))
Label(root, image=color_box, bg='#f2f3f5').place(x=10, y=20)

eraser = PhotoImage(file=resource_path("icons/eraser1.png"))
Button(root, image=eraser, bg="#f2f3f5", command=set_eraser).place(x=30, y=canvas_height - 150)

import_image = PhotoImage(file=resource_path("icons/add_image.png"))
Button(root, image=import_image, bg="white", command=insertimage).place(x=30, y=canvas_height - 100)

colors = Canvas(root, bg="#fff", width=37, height=300, bd=0)
colors.place(x=30, y=60)
display_pallete()

# Define on_canvas_click before it's used in binding
def on_button1_press(event):
    """Combined function for handling Button-1 press events for drawing and text"""
    global start_x, start_y, current_x, current_y, panning, last_x, last_y, active_tool
    
    # Apply zoom and pan transformations to coordinates
    canvas_x = (event.x - pan_x) / zoom_factor
    canvas_y = (event.y - pan_y) / zoom_factor
    
    start_x, start_y = canvas_x, canvas_y
    current_x, current_y = canvas_x, canvas_y
    
    # Check if text tool is active and handle it
    if active_tool == "text":
        text = simpledialog.askstring("Input", "Enter text:")
        if text:
            canvas.create_text(canvas_x, canvas_y, text=text, fill=color, 
                              font=(text_font, int(slider.get()) * 2))
            save_canvas_state()
            # Reset tool to avoid multiple text entries
            active_tool = None
            safe_update_status("Text added.")
    
    # Start panning if middle button is pressed
    if event.num == 2:  # Middle button
        panning = True
        last_x, last_y = event.x, event.y

# Canvas event bindings
canvas.bind('<Button-1>', on_button1_press)
canvas.bind('<B1-Motion>', addline)
canvas.bind('<ButtonRelease-1>', lambda event: handle_release(event))
canvas.bind('<Button-2>', on_button1_press)  # Middle button for panning
canvas.bind('<B2-Motion>', addline)  # Middle button motion for panning
canvas.bind('<ButtonRelease-2>', lambda event: handle_release(event))  # Middle button release
canvas.bind('<MouseWheel>', lambda event: zoom_in() if event.delta > 0 else zoom_out())  # Mouse wheel for zoom

# slider setup
current_value = tk.DoubleVar()

def get_current_value():
    return '{: .2f}'.format(current_value.get())

def slider_changed(event):
    value_label.configure(text=get_current_value())

slider = ttk.Scale(root, from_=1, to=10, orient="horizontal", command=slider_changed, variable=current_value)
slider.place(x=30, y=canvas_height - 40)

value_label = ttk.Label(root, text=get_current_value())
value_label.place(x=27, y=canvas_height - 20)

# chatbot setup
# Define UI toggle functions first
def toggle_chatbot():
    if 'chatbot_frame' in globals() and chatbot_frame.winfo_ismapped():
        chatbot_frame.place_forget()
    else:
        chatbot_frame.place(x=canvas_width + canvas_x-200, y=200, width=300, height=600)

def toggle_chatbotvai():
    if 'chatbotv_frame' in globals() and chatbotv_frame.winfo_ismapped():
        chatbotv_frame.place_forget()
    else:
        chatbotv_frame.place(x=canvas_width + canvas_x -300, y=200, width=300, height=600)

def minimize_chatbot():
    chatbot_frame.place_forget()

def minimize_chatbotvai():
    chatbotv_frame.place_forget()

def handle_query():
    if 'query_entry' not in globals() or 'query_output' not in globals():
        return
    
    query = query_entry.get()
    if query:
        bot = TutorChatBot()
        output = bot.respond(query)
        query_output.config(state='normal')
        query_output.delete("1.0", END)
        query_output.insert(END, output.content)
        query_output.config(state='disabled')

def handlevai_query():
    if 'query_entryv' not in globals() or 'queryv_output' not in globals():
        return
    
    user_input = query_entryv.get()
    if user_input:
        # Show waiting message
        queryv_output.config(state='normal')
        queryv_output.delete("1.0", END)
        queryv_output.insert(END, "Processing your query about the whiteboard content...\nPlease wait.")
        queryv_output.config(state='disabled')
        
        # The ScreenAnalyzer class has its own screenshot capture
        try:
            # Create analyzer and get response
            analyzer = ScreenAnalyzer()
            outputvai = analyzer.analyze_screen(user_input)
            
            # Display results
            queryv_output.config(state='normal')
            queryv_output.delete("1.0", END)
            queryv_output.insert(END, outputvai)
            queryv_output.config(state='disabled')
            
            # Provide feedback
            safe_update_status(f"Visual query processed: {user_input}")
        except Exception as e:
            # Handle errors
            queryv_output.config(state='normal')
            queryv_output.delete("1.0", END)
            queryv_output.insert(END, f"Error processing query: {str(e)}\n\nPlease try again.")
            queryv_output.config(state='disabled')
            safe_update_status("Error in visual query processing")

def capture_screen():
    """Capture current canvas as screenshot for the visual AI"""
    global screen_capture
    # Get the bbox of the canvas
    x = root.winfo_rootx() + canvas.winfo_x()
    y = root.winfo_rooty() + canvas.winfo_y()
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    
    # Capture the screen area
    screen_capture = ImageGrab.grab(bbox=(x, y, x+width, y+height))
    
    # Show confirmation with safe function
    safe_update_status("Screen captured for visual analysis")

chatbot_icon = PhotoImage(file=resource_path("icons/chatbot.png"))
chatbot_button = Button(
    root,
    image=chatbot_icon,
    command=toggle_chatbot,
    bg="#f2f3f5",
    activebackground="#e1e3e6",
    borderwidth=0,
    cursor="hand2"
)
chatbot_button.place(x=canvas_width + canvas_x - 50, y=canvas_height - 50)


chatbot_frame = Frame(
    root,
    bg="white",
    bd=0,
    highlightthickness=1,
    highlightbackground="#e0e0e0"
)


header_frame = Frame(chatbot_frame, bg="#4a90e2", height=40)
header_frame.pack(fill="x", pady=(0, 10))

Label(
    header_frame,
    text="Chat Assistant",
    bg="#4a90e2",
    fg="white",
    font=("Helvetica", 12, "bold")
).pack(side="left", padx=10, pady=8)


Label(
    chatbot_frame,
    text="How can I help you?",
    bg="white",
    fg="#2c3e50",
    font=("Helvetica", 10)
).pack(anchor=W, padx=12, pady=(0, 5))


query_entry = Entry(
    chatbot_frame,
    width=30,
    font=("Helvetica", 11),
    bd=1,
    relief="solid",
    bg="#f8f9fa"
)
query_entry.pack(padx=12, pady=(0, 10))


Button(
    chatbot_frame,
    text="Send Message",
    command=handle_query,
    bg="#4a90e2",
    fg="white",
    font=("Helvetica", 10, "bold"),
    relief="flat",
    padx=15,
    pady=5,
    cursor="hand2"
).pack(pady=(0, 10))

# chat output area with frame
output_frame = Frame(chatbot_frame, bg="#f8f9fa", padx=2, pady=2)
output_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

query_output = Text(
    output_frame,
    height=25,
    width=35,
    font=("Helvetica", 10),
    state='disabled',
    bg="#f8f9fa",
    relief="flat",
    padx=8,
    pady=8
)
query_output.pack(fill="both", expand=True)

# added scrollbar
scrollbar = Scrollbar(output_frame)
scrollbar.pack(side="right", fill="y")
query_output.config(yscrollcommand=scrollbar.set)
scrollbar.config(command=query_output.yview)

#minimize button
minimize_button = Button(
    header_frame,
    text="−",
    command=minimize_chatbot,
    bg="#4a90e2",
    fg="white",
    font=("Helvetica", 16),
    relief="flat",
    bd=0,
    cursor="hand2"
)
minimize_button.pack(side="right", padx=10)

# add hover effects for buttons
def on_enter(e):
    e.widget['background'] = '#357abd'

def on_leave(e):
    e.widget['background'] = '#4a90e2'

# add hover effects to buttons
for button in chatbot_frame.winfo_children():
    if isinstance(button, Button) and button['bg'] == '#4a90e2':
        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)

# Forward declaration of insert_document to be used before its full definition
def insert_document():
    global slides, current_slide
    file_path = filedialog.askopenfilename(
        initialdir=os.getcwd(),
        title="Select Document",
        filetypes=[("PDF files", "*.pdf"), ("Text files", "*.txt"), ("All files", "*.*")]
    )
    
    if not file_path:
        return
    
    if file_path.lower().endswith('.pdf'):
        try:
            reader = PdfReader(file_path)
            slides = []
            current_slide = 0
            
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    slides.append(text)
                else:
                    slides.append("[No text content on this page]")
                    
            if slides:
                display_slide()
                safe_update_status(f"Loaded {len(slides)} slides. Current: {current_slide+1}/{len(slides)}")
            else:
                messagebox.showinfo("Document", "No readable content found in the document.")
        except Exception as e:
            messagebox.showerror("PDF Error", f"Could not read PDF: {str(e)}")
    elif file_path.lower().endswith('.txt'):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                slides = []
                current_slide = 0
                
                if len(content) > 2000:
                    # Split into reasonably sized chunks
                    chunk_size = 1500
                    slides = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
                else:
                    slides = content.split('\n\n')
                    
                if slides:
                    display_slide()
                    safe_update_status(f"Loaded {len(slides)} slides. Current: {current_slide+1}/{len(slides)}")
                else:
                    messagebox.showinfo("Document", "No readable content found in the document.")
        except Exception as e:
            messagebox.showerror("File Error", f"Could not read file: {str(e)}")

# document upload setup - restore the document upload feature
document_icon = PhotoImage(file=resource_path("icons/document_icon.png"))
document_button = Button(root, image=document_icon, bg="#f2f3f5", borderwidth=0, command=insert_document)
document_button.place(x=canvas_width + canvas_x - 300, y=canvas_height - 50)

# Bottom toolbar buttons
toolbar_y = canvas_height - 50
# Define common button style parameters
toolbar_button_style = {
    'font': ('Segoe UI', 10),
    'relief': 'flat',
    'borderwidth': 0,
    'padx': 15,
    'pady': 8,
    'cursor': 'hand2',
    'highlightthickness': 0
}

# Create a horizontal layout with small gaps between buttons
# First row - Drawing tools
Button(root,
    text="Rectangle",
    command=set_rectangle_tool,
    bg="#3498db",  # Modern blue
    fg="white",
    activebackground="#2980b9",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 100, y=toolbar_y)

Button(root,
    text="Oval",
    command=set_oval_tool,
    bg="#2ecc71",  # Modern green
    fg="white",
    activebackground="#27ae60",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 210, y=toolbar_y)

Button(root,
    text="Text",
    command=set_text_tool,
    bg="#e67e22",  # Modern orange
    fg="white",
    activebackground="#d35400",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 320, y=toolbar_y)

Button(root,
    text="Clear Screen",
    command=new_canvas,
    bg="#e74c3c",  # Modern red
    fg="white",
    activebackground="#c0392b",
    width=12,
    **toolbar_button_style
).place(x=canvas_x + 430, y=toolbar_y)

# Triangle tool button
Button(root,
    text="Triangle",
    command=set_triangle_tool,
    bg="#9b59b6",  # Purple
    fg="white",
    activebackground="#8e44ad",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 540, y=toolbar_y)

# Square tool button
Button(root,
    text="Square",
    command=set_square_tool,
    bg="#2ecc71",  # Modern green
    fg="white",
    activebackground="#27ae60",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 650, y=toolbar_y)

# Add second row of toolbar buttons
toolbar_y2 = toolbar_y - 50  # Position above the first toolbar

# Eraser button
Button(root,
    text="Eraser",
    command=set_eraser,
    bg="#95a5a6",  # Light gray
    fg="white",
    activebackground="#7f8c8d",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 100, y=toolbar_y2)

# Fill toggle button
fill_toggle = Button(root,
    text="Fill: Off",
    command=toggle_fill,
    bg="#e74c3c",  # Red
    fg="white",
    activebackground="#c0392b",
    width=10,
    **toolbar_button_style
)
fill_toggle.place(x=canvas_x + 210, y=toolbar_y2)

# Add a modern label
Label(root, text="Smart White Board", bg="#ffffff", fg="#2c3e50", font=("Segoe UI", 16, "bold")).place(x=canvas_x + 20, y=20)

# Restore the visual query assistant feature
doubt_button = Button(root, 
    text="Ask doubt ✋", 
    command=toggle_chatbotvai,
    font=("Helvetica", 11, "bold"),
    bg="#4a90e2",  # Modern blue color
    fg="white",
    relief="flat",
    padx=15,
    pady=8,
    cursor="hand2"
).place(x=canvas_width + canvas_x - 500, y=canvas_height - 50)

chatbotv_frame = Frame(
    root, 
    bg="#ffffff",
    bd=0,
    highlightthickness=1,
    highlightbackground="#e0e0e0"
)


header_frame = Frame(chatbotv_frame, bg="#4a90e2", height=40)
header_frame.pack(fill="x", pady=(0, 10))

Label(
    header_frame,
    text="Whiteboard Analysis Assistant",
    bg="#4a90e2",
    fg="white",
    font=("Helvetica", 12, "bold")
).pack(side="left", padx=10, pady=8)


Label(
    chatbotv_frame,
    text="Ask a question about what's on the whiteboard:",
    bg="white",
    fg="#2c3e50",
    font=("Helvetica", 10)
).pack(anchor=W, padx=12, pady=(0, 5))

query_entryv = Entry(
    chatbotv_frame,
    width=30,
    font=("Helvetica", 11),
    bd=1,
    relief="solid",
    bg="#f8f9fa"
)
query_entryv.pack(padx=12, pady=(0, 10))

# Add a button frame to hold multiple buttons horizontally
button_frame = Frame(chatbotv_frame, bg="white")
button_frame.pack(pady=(0, 10))

# Add submit button - we don't need a separate capture button as the analyzer does that
Button(
    button_frame,
    text="Analyze Whiteboard",
    command=handlevai_query,
    bg="#4a90e2",  # Blue
    fg="white",
    font=("Helvetica", 10, "bold"),
    relief="flat",
    padx=15,
    pady=5,
    cursor="hand2"
).pack(side=LEFT, padx=5)

# chat output area with frame
output_frame = Frame(chatbotv_frame, bg="#f8f9fa", padx=2, pady=2)
output_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

queryv_output = Text(
    output_frame,
    height=25,
    width=30,
    font=("Helvetica", 10),
    state='disabled',
    bg="#f8f9fa",
    relief="flat",
    padx=8,
    pady=8
)
queryv_output.pack(fill="both", expand=True)

#scrollbar for output
scrollbar = Scrollbar(output_frame)
scrollbar.pack(side="right", fill="y")
queryv_output.config(yscrollcommand=scrollbar.set)
scrollbar.config(command=queryv_output.yview)

# modern minimize button
minimize_buttonv = Button(
    header_frame,
    text="−",
    command=minimize_chatbotvai,
    bg="#4a90e2",
    fg="white",
    font=("Helvetica", 16),
    relief="flat",
    bd=0,
    cursor="hand2"
)
minimize_buttonv.pack(side="right", padx=10)

# add hover effects for buttons
def on_enter(e):
    e.widget['background'] = '#357abd'

def on_leave(e):
    e.widget['background'] = '#4a90e2'

# Bind hover events to all blue buttons
for button in chatbotv_frame.winfo_children():
    if isinstance(button, Button) and button['bg'] == '#4a90e2':
        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)

def set_tool(tool):
    """General function to set the active tool"""
    global active_tool
    active_tool = tool
    
    # Add any specific handling for special tools here
    if tool == "eraser":
        global color
        color = "white"

# slides handling
slides = []
current_slide = 0

def display_slide():
    global slides, current_slide
    if not slides or current_slide < 0 or current_slide >= len(slides):
        return
        
    canvas.delete('all')
    
    slide_text = slides[current_slide]
    
    # Add margin and calculate text width
    margin = 20
    text_width = canvas_width - 2 * margin
    
    # Create text on canvas
    canvas.create_text(
        margin, margin,
        anchor=NW,
        text=slide_text,
        font=("Arial", 12),
        fill="black",
        width=text_width
    )
    
    # Add slide number indicator
    slide_indicator = f"Slide {current_slide+1}/{len(slides)}"
    canvas.create_text(
        canvas_width - margin, canvas_height - margin,
        anchor=SE,
        text=slide_indicator,
        font=("Arial", 10),
        fill="#666666"
    )
    
    # Update slide counter
    safe_update_status(f"Slide {current_slide+1}/{len(slides)}")

def next_slide():
    global current_slide
    if current_slide < len(slides) - 1:
        current_slide += 1
        display_slide()
        
        # Update button states if they exist
        if 'prev_slide_btn' in globals() and 'next_slide_btn' in globals():
            try:
                prev_slide_btn.config(state=NORMAL)
                next_slide_btn.config(state=DISABLED if current_slide >= len(slides)-1 else NORMAL)
            except (NameError, TclError):
                pass

def previous_slide():
    global current_slide
    if current_slide > 0:
        current_slide -= 1
        display_slide()
        
        # Update button states if they exist
        if 'prev_slide_btn' in globals() and 'next_slide_btn' in globals():
            try:
                prev_slide_btn.config(state=DISABLED if current_slide <= 0 else NORMAL)
                next_slide_btn.config(state=NORMAL)
            except (NameError, TclError):
                pass

def add_slide():
    """Add a new blank slide after the current one"""
    global slides, current_slide
    
    if not slides:
        slides = [""]
        current_slide = 0
    else:
        slides.insert(current_slide + 1, "")
        current_slide += 1
    
    canvas.delete('all')
    save_canvas_state()
    
    # Update button states
    if prev_slide_btn:
        prev_slide_btn.config(state=NORMAL if current_slide > 0 else DISABLED)
    if next_slide_btn:
        next_slide_btn.config(state=NORMAL if current_slide < len(slides)-1 else DISABLED)
    
    safe_update_status(f"Added new slide. Current: {current_slide+1}/{len(slides)}")

def delete_slide():
    """Delete the current slide"""
    global slides, current_slide
    
    if not slides or len(slides) <= 1:
        # Don't delete if it's the only slide
        return
    
    slides.pop(current_slide)
    if current_slide >= len(slides):
        current_slide = len(slides) - 1
    
    display_slide()
    
    # Update button states
    if prev_slide_btn:
        prev_slide_btn.config(state=NORMAL if current_slide > 0 else DISABLED)
    if next_slide_btn:
        next_slide_btn.config(state=NORMAL if current_slide < len(slides)-1 else DISABLED)
    
    safe_update_status(f"Deleted slide. Current: {current_slide+1}/{len(slides)}")

def save_slides():
    """Save all slides to a file"""
    file_path = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        filetypes=[("PDF Document", "*.pdf"), ("Text File", "*.txt")],
        title="Save Slides"
    )
    
    if not file_path:
        return
    
    if file_path.endswith('.pdf'):
        # Create a PDF with one page per slide
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.lib.pagesizes import letter
        
        c = pdf_canvas.Canvas(file_path, pagesize=letter)
        for slide in slides:
            c.drawString(72, 720, slide[:1000])  # Simple text rendering
            c.showPage()
        c.save()
    elif file_path.endswith('.txt'):
        # Save as text file
        with open(file_path, 'w') as f:
            f.write('\n\n'.join(slides))
    
    safe_update_status(f"Saved {len(slides)} slides to {os.path.basename(file_path)}")

# Create presentation controls
# Define button style parameters
button_style = {
    'font': ('Segoe UI', 10),
    'relief': 'flat',
    'borderwidth': 0,
    'padx': 15,
    'pady': 8,
    'cursor': 'hand2',
    'highlightthickness': 0
}

presentation_frame = Frame(root, bg="#f2f3f5", bd=1, relief=SOLID)
presentation_frame.place(x=canvas_width - 400, y=canvas_height + 20, width=400, height=40)

prev_slide_btn = Button(presentation_frame, 
    text="◀ Previous",
    command=previous_slide,
    bg="#8e44ad",
    fg="white",
    state=DISABLED,
    **button_style
)
prev_slide_btn.pack(side=LEFT, padx=5)

next_slide_btn = Button(presentation_frame,
    text="Next ▶",
    command=next_slide,
    bg="#3498db",
    fg="white",
    state=DISABLED,
    **button_style
)
next_slide_btn.pack(side=LEFT, padx=5)

Button(presentation_frame,
    text="Add Slide",
    command=add_slide,
    bg="#2ecc71",
    fg="white",
    **button_style
).pack(side=LEFT, padx=5)

Button(presentation_frame,
    text="Delete Slide",
    command=delete_slide,
    bg="#e74c3c",
    fg="white",
    **button_style
).pack(side=LEFT, padx=5)

Button(presentation_frame,
    text="Load Document",
    command=insert_document,
    bg="#f39c12",
    fg="white",
    **button_style
).pack(side=LEFT, padx=5)

Button(presentation_frame,
    text="Save Slides",
    command=save_slides,
    bg="#34495e",
    fg="white",
    **button_style
).pack(side=LEFT, padx=5)

# Start autosave timer
root.after(autosave_interval, autosave)

# Keyboard shortcuts
def handle_keypress(event):
    global active_tool
    # Ctrl+Z for Undo
    if event.state & 0x4 and event.keysym == 'z':
        undo()
    # Ctrl+Y for Redo
    elif event.state & 0x4 and event.keysym == 'y':
        redo()
    # Ctrl+S for Save
    elif event.state & 0x4 and event.keysym == 's':
        save_session()
    # Ctrl+O for Open
    elif event.state & 0x4 and event.keysym == 'o':
        load_session()
    # Ctrl+N for New
    elif event.state & 0x4 and event.keysym == 'n':
        new_canvas()
    # Delete key for Eraser
    elif event.keysym == 'Delete':
        set_eraser()
    # Escape key to cancel tool
    elif event.keysym == 'Escape':
        active_tool = None
    # Arrow keys for navigation
    elif event.keysym == 'Right':
        next_slide()
    elif event.keysym == 'Left':
        previous_slide()
    # Plus/Minus for zoom
    elif event.keysym == 'plus':
        zoom_in()
    elif event.keysym == 'minus':
        zoom_out()

# Bind keyboard shortcuts
root.bind('<Key>', handle_keypress)

# Create context menu for right-click options
context_menu = Menu(root, tearoff=0)
context_menu.add_command(label="Cut", command=lambda: root.event_generate("<<Cut>>"))
context_menu.add_command(label="Copy", command=lambda: root.event_generate("<<Copy>>"))
context_menu.add_command(label="Paste", command=lambda: root.event_generate("<<Paste>>"))
context_menu.add_separator()
context_menu.add_command(label="Select All", command=lambda: root.event_generate("<<SelectAll>>"))
context_menu.add_separator()
context_menu.add_command(label="Clear Canvas", command=new_canvas)
context_menu.add_command(label="Change Color", command=choose_color)

def show_context_menu(event):
    context_menu.post(event.x_root, event.y_root)

canvas.bind("<Button-3>", show_context_menu)

# Initialize canvas with white background
new_canvas()

# Start with an initial state in history
save_canvas_state()

# Update window title
root.title(f"Smart White Board - {session_name}")

# Show welcome message
safe_update_status("Welcome to Smart White Board! Ready to draw.")

# Add more buttons to the second row
Button(root,
    text="Undo",
    command=undo,
    bg="#3498db",  # Blue
    fg="white",
    activebackground="#2980b9",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 320, y=toolbar_y2)

Button(root,
    text="Redo",
    command=redo,
    bg="#9b59b6",  # Purple
    fg="white",
    activebackground="#8e44ad",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 430, y=toolbar_y2)

Button(root,
    text="Color Picker",
    command=choose_color,
    bg="#f39c12",  # Orange
    fg="white",
    activebackground="#d35400",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 540, y=toolbar_y2)

Button(root,
    text="Export",
    command=export_canvas,
    bg="#16a085",  # Teal
    fg="white",
    activebackground="#1abc9c",
    width=10,
    **toolbar_button_style
).place(x=canvas_x + 650, y=toolbar_y2)

# Color indicator
color_indicator = Label(root, bg=color, width=4, height=2)
color_indicator.place(x=canvas_x + 760, y=toolbar_y2+10)

def generate_image_from_text():
    """Generate image from text using Hugging Face Inference Client"""
    # Ask user for text input
    text = simpledialog.askstring("Image Generation", "Enter text to generate image:")
    if not text:
        return
        
    try:
        # Show loading message
        safe_update_status("Generating image... Please wait.")
        
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                # Generate image using Inference Client
                pil_img = client.text_to_image(
                    text,
                    model="stabilityai/stable-diffusion-2-1-base",
                    negative_prompt="blurry, bad quality",
                    guidance_scale=7.5,
                    num_inference_steps=30
                )
                
                # If we get here, image generation was successful
                break
                
            except Exception as e:
                if "server unavailable" in str(e).lower() or "temporarily" in str(e).lower():
                    if attempt < max_retries - 1:
                        safe_update_status(f"Server busy. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise Exception("Server is temporarily unavailable. Please try again later.")
                else:
                    raise e
        
        # Resize image if needed
        max_size = (800, 800)
        pil_img.thumbnail(max_size, Image.LANCZOS)
        
        # Convert to PhotoImage
        f_img = ImageTk.PhotoImage(pil_img)
        
        # Center the image on the canvas
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        img_width = f_img.width()
        img_height = f_img.height()
        center_x = (canvas_width - img_width) // 2
        center_y = (canvas_height - img_height) // 2
        
        # Create image on canvas
        canvas.create_image(center_x, center_y, image=f_img, anchor=NW)
        canvas.image = f_img  # Keep reference to prevent garbage collection
        
        # Save state after adding image
        save_canvas_state()
        safe_update_status("Image generated successfully!")
        
    except Exception as e:
        error_message = str(e)
        if "server unavailable" in error_message.lower() or "temporarily" in error_message.lower():
            messagebox.showerror("Server Busy", "The image generation server is currently busy. Please try again in a few minutes.")
        else:
            messagebox.showerror("Error", f"Could not generate image: {error_message}")
        safe_update_status("Image generation failed")

# Add image generator button before main loop
image_gen_button = Button(
    root,
    text="AI\nImage",
    command=generate_image_from_text,
    bg="#4a90e2",  # Blue color
    fg="white",
    activebackground="#357abd",
    borderwidth=0,
    cursor="hand2",
    font=("Arial", 9, "bold"),
    width=4,
    height=2,
    relief="flat"
)
image_gen_button.place(x=canvas_width + canvas_x - 150, y=canvas_height - 50)

# Add tooltip
tooltip = Label(root, text="Generate Image from Text", bg="#ffffe0", relief="solid", borderwidth=1)
tooltip.place_forget()

def show_tooltip(event):
    tooltip.place(x=event.x_root, y=event.y_root - 30)

def hide_tooltip(event):
    tooltip.place_forget()

image_gen_button.bind("<Enter>", show_tooltip)
image_gen_button.bind("<Leave>", hide_tooltip)

# Start the main loop
root.mainloop()