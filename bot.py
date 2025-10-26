import os
import logging
import psycopg2
from psycopg2 import sql
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configura il logging per vedere gli errori su Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- GESTIONE DATABASE POSTGRES ---

def get_db_connection():
    """Si connette al database Postgres usando l'URL fornito da Render."""
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        return conn
    except Exception as e:
        logger.error(f"Errore di connessione al database: {e}")
        return None

def setup_database():
    """Crea le tabelle necessarie se non esistono."""
    conn = get_db_connection()
    if conn is None:
        return
        
    try:
        with conn.cursor() as cur:
            # Tabella per i reparti
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reparti (
                    chat_id BIGINT NOT NULL,
                    reparto_nome TEXT NOT NULL,
                    PRIMARY KEY (chat_id, reparto_nome)
                );
            """)
            # Tabella per i membri dei reparti
            cur.execute("""
                CREATE TABLE IF NOT EXISTS membri (
                    chat_id BIGINT NOT NULL,
                    reparto_nome TEXT NOT NULL,
                    user_id BIGINT NOT NULL,
                    user_name TEXT,
                    PRIMARY KEY (chat_id, reparto_nome, user_id),
                    FOREIGN KEY (chat_id, reparto_nome) 
                        REFERENCES reparti (chat_id, reparto_nome) 
                        ON DELETE CASCADE
                );
            """)
        conn.commit()
        logger.info("Tabelle del database verificate/create con successo.")
    except Exception as e:
        logger.error(f"Errore durante la creazione delle tabelle: {e}")
    finally:
        conn.close()

# --- FUNZIONI HELPER ---

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Controlla se l'utente che ha inviato il comando è un admin del gruppo."""
    if update.message.chat.type == 'private':
        return True  # L'utente è admin di sé stesso in chat privata
    
    try:
        chat_admins = await context.bot.get_chat_administrators(update.message.chat_id)
        admin_ids = [admin.user.id for admin in chat_admins]
        return update.message.from_user.id in admin_ids
    except Exception as e:
        logger.error(f"Errore nel controllare i permessi admin: {e}")
        await update.message.reply_text("Non riesco a verificare i tuoi permessi. Assicurati che io sia admin nel gruppo.")
        return False

# --- COMANDI DI CONFIGURAZIONE ---

async def crea_reparto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Admin) Crea un nuovo reparto. Es: /crea_reparto @aero"""
    if not await is_admin(update, context):
        await update.message.reply_text("Questo comando può essere usato solo dagli admin del gruppo.")
        return

    try:
        reparto_nome = context.args[0].lower()
        if not reparto_nome.startswith('@'):
            await update.message.reply_text("Formato errato. Il nome del reparto deve iniziare con @ (es: /crea_reparto @aero)")
            return
            
        chat_id = update.message.chat_id
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reparti (chat_id, reparto_nome) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                (chat_id, reparto_nome)
            )
        conn.commit()
        await update.message.reply_text(f"Reparto {reparto_nome} creato con successo!")
    except (IndexError, TypeError):
        await update.message.reply_text("Uso: /crea_reparto @nome_reparto")
    except Exception as e:
        logger.error(f"Errore in /crea_reparto: {e}")
        await update.message.reply_text(f"Errore: il reparto {reparto_nome} esiste già o c'è stato un problema.")
    finally:
        if conn:
            conn.close()

async def aggiungi_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Admin) Aggiunge un utente a un reparto. Uso: Rispondi a un utente con /aggiungi_membro @aero"""
    if not await is_admin(update, context):
        await update.message.reply_text("Questo comando può essere usato solo dagli admin del gruppo.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Devi rispondere al messaggio di un utente per aggiungerlo.")
        return

    try:
        reparto_nome = context.args[0].lower()
        chat_id = update.message.chat_id
        utente_da_aggiungere = update.message.reply_to_message.from_user
        
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Prima controlla se il reparto esiste
            cur.execute("SELECT * FROM reparti WHERE chat_id = %s AND reparto_nome = %s;", (chat_id, reparto_nome))
            if cur.fetchone() is None:
                await update.message.reply_text(f"Il reparto {reparto_nome} non esiste. Crealo prima con /crea_reparto {reparto_nome}")
                return

            # Aggiungi il membro
            cur.execute(
                "INSERT INTO membri (chat_id, reparto_nome, user_id, user_name) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING;",
                (chat_id, reparto_nome, utente_da_aggiungere.id, utente_da_aggiungere.full_name)
            )
        conn.commit()
        await update.message.reply_text(f"Utente {utente_da_aggiungere.full_name} aggiunto a {reparto_nome}.")
    except (IndexError, TypeError):
        await update.message.reply_text("Uso: Rispondi a un utente con /aggiungi_membro @nome_reparto")
    except Exception as e:
        logger.error(f"Errore in /aggiungi_membro: {e}")
        await update.message.reply_text("Si è verificato un errore.")
    finally:
        if conn:
            conn.close()

async def rimuovi_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Admin) Rimuove un utente da un reparto. Uso: Rispondi a un utente con /rimuovi_membro @aero"""
    if not await is_admin(update, context):
        await update.message.reply_text("Questo comando può essere usato solo dagli admin del gruppo.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Devi rispondere al messaggio di un utente per rimuoverlo.")
        return

    try:
        reparto_nome = context.args[0].lower()
        chat_id = update.message.chat_id
        utente_da_rimuovere = update.message.reply_to_message.from_user

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM membri WHERE chat_id = %s AND reparto_nome = %s AND user_id = %s;",
                (chat_id, reparto_nome, utente_da_rimuovere.id)
            )
        conn.commit()
        if conn.cursor().rowcount == 0:
             await update.message.reply_text(f"L'utente {utente_da_rimuovere.full_name} non era in {reparto_nome}.")
        else:
            await update.message.reply_text(f"Utente {utente_da_rimuovere.full_name} rimosso da {reparto_nome}.")
    except (IndexError, TypeError):
        await update.message.reply_text("Uso: Rispondi a un utente con /rimuovi_membro @nome_reparto")
    except Exception as e:
        logger.error(f"Errore in /rimuovi_membro: {e}")
        await update.message.reply_text("Si è verificato un errore.")
    finally:
        if conn:
            conn.close()

async def lista_reparto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Elenca tutti i membri di un reparto. Es: /lista_reparto @aero"""
    try:
        reparto_nome = context.args[0].lower()
        chat_id = update.message.chat_id
        
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, user_name FROM membri WHERE chat_id = %s AND reparto_nome = %s;",
                (chat_id, reparto_nome)
            )
            membri = cur.fetchall()

        if not membri:
            await update.message.reply_text(f"Nessun membro trovato per il reparto {reparto_nome}.")
            return

        messaggio = f"Membri del reparto {reparto_nome}:\n"
        for user_id, user_name in membri:
            # Crea un link menzionabile (ma non notifica) per la lista
            messaggio += f"- {user_name} ([ID: {user_id}])\n" 
            
        await update.message.reply_text(messaggio)
    except (IndexError, TypeError):
        await update.message.reply_text("Uso: /lista_reparto @nome_reparto")
    except Exception as e:
        logger.error(f"Errore in /lista_reparto: {e}")
        await update.message.reply_text("Si è verificato un errore.")
    finally:
        if conn:
            conn.close()

# --- GESTORE MESSAGGI (CORE LOGIC) ---

async def gestore_messaggi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analizza ogni messaggio e tagga i reparti menzionati."""
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    testo_messaggio = update.message.text.lower()
    
    conn = get_db_connection()
    if conn is None:
        return
        
    try:
        with conn.cursor() as cur:
            # 1. Trova tutti i reparti registrati per questo gruppo
            cur.execute("SELECT reparto_nome FROM reparti WHERE chat_id = %s;", (chat_id,))
            reparti_registrati = cur.fetchall()
            
            reparto_da_taggare = None
            for (reparto_nome,) in reparti_registrati:
                if reparto_nome in testo_messaggio:
                    reparto_da_taggare = reparto_nome
                    break # Trovato il primo reparto, mi fermo
            
            if reparto_da_taggare:
                # 2. Trova tutti i membri di quel reparto
                cur.execute(
                    "SELECT user_id FROM membri WHERE chat_id = %s AND reparto_nome = %s;",
                    (chat_id, reparto_da_taggare)
                )
                membri_da_taggare = cur.fetchall()
                
                if membri_da_taggare:
                    tags = []
                    # \u200B è uno "spazio invisibile" per creare il link
                    for (user_id,) in membri_da_taggare:
                        tags.append(f"[\u200B](tg://user?id={user_id})")
                    
                    messaggio_tags = f"🔔 Chiamata per {reparto_da_taggare}:\n" + " ".join(tags)
                    
                    # Invia il messaggio di tag come risposta al messaggio originale
                    await update.message.reply_text(messaggio_tags, parse_mode='Markdown')
                    
    except Exception as e:
        logger.error(f"Errore nel gestore_messaggi: {e}")
    finally:
        conn.close()

# --- MAIN ---

def main():
    """Avvia il bot."""
    
    # Prende il token dalla Variabile d'Ambiente
    TOKEN = os.environ.get('TELEGRAM_TOKEN')
    if not TOKEN:
        logger.critical("Variabile d'ambiente 'TELEGRAM_TOKEN' non trovata!")
        return
        
    # Prende l'URL del DB dalla Variabile d'Ambiente
    DB_URL = os.environ.get('DATABASE_URL')
    if not DB_URL:
        logger.critical("Variabile d'ambiente 'DATABASE_URL' non trovata!")
        return

    logger.info("Avvio setup database...")
    setup_database()

    application = Application.builder().token(TOKEN).build()

    # Comandi di configurazione
    application.add_handler(CommandHandler("crea_reparto", crea_reparto))
    application.add_handler(CommandHandler("aggiungi_membro", aggiungi_membro))
    application.add_handler(CommandHandler("rimuovi_membro", rimuovi_membro))
    application.add_handler(CommandHandler("lista_reparto", lista_reparto))

    # Gestore dei messaggi per i tag
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gestore_messaggi))

    logger.info("Bot in avvio...")
    application.run_polling()

if __name__ == "__main__":
    main()
