import os
import logging
from aiogram import Bot
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup

LOGO_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "logo_horizontal.png"
))

LOGO_FILE_ID = None

async def send_menu_with_logo(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup = None,
    parse_mode: str = "Markdown",
    message_to_edit: Message = None
) -> Message:
    """
    Sends or edits a menu message ensuring the logo horizontal image is always displayed above the text.
    Uses file_id caching to maximize performance and avoid uploading the logo multiple times to Telegram.
    """
    global LOGO_FILE_ID
    photo = LOGO_FILE_ID if LOGO_FILE_ID else (FSInputFile(LOGO_PATH) if os.path.exists(LOGO_PATH) else None)
    
    if not photo:
        logging.warning(f"Logo not found at {LOGO_PATH}. Falling back to text-only message.")
        if message_to_edit:
            try:
                if message_to_edit.photo:
                    return await message_to_edit.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                else:
                    return await message_to_edit.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as e:
                logging.error(f"Error editing message (fallback): {e}")
        return await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

    # If we have a message to edit
    if message_to_edit:
        try:
            if message_to_edit.photo:
                # The message already has a photo/logo. We can simply edit the caption and reply markup!
                return await message_to_edit.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                # The message to edit does not have a photo. Since we cannot change a text message to a photo message in-place,
                # we delete the old text message to avoid clutter and send a fresh photo message.
                try:
                    await message_to_edit.delete()
                except Exception as e:
                    logging.warning(f"Could not delete old text message: {e}")
        except Exception as e:
            logging.error(f"Error editing message with photo: {e}")

    # Send a new message with the photo
    try:
        sent_msg = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        if not LOGO_FILE_ID and sent_msg.photo:
            LOGO_FILE_ID = sent_msg.photo[-1].file_id
            logging.info(f"Cached logo file_id: {LOGO_FILE_ID}")
        return sent_msg
    except Exception as e:
        logging.error(f"Error sending photo menu: {e}")
        # Final fallback to standard text message
        return await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
