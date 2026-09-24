-- Script de création de la base de données et de l'utilisateur applicatif
-- pour le projet "Outil de contrôle de la fraude sur la mutuelle de santé".
--
-- Utilisation :
--   sudo mysql < setup_mysql.sql
--
-- Ce script est idempotent : il peut être relancé sans erreur.

CREATE DATABASE IF NOT EXISTS mutuelle_sante
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Remplacer le mot de passe ci-dessous avant d'exécuter le script, et
-- reporter la même valeur dans backend/.env (DB_PASSWORD).
CREATE USER IF NOT EXISTS 'mutuelle_app'@'localhost' IDENTIFIED BY 'a-remplacer';

GRANT ALL PRIVILEGES ON mutuelle_sante.* TO 'mutuelle_app'@'localhost';

-- Pour lancer la suite de tests : Django crée puis détruit une base temporaire
-- préfixée « test_ », sur laquelle l'utilisateur applicatif doit avoir les droits.
GRANT ALL PRIVILEGES ON `test_mutuelle_sante`.* TO 'mutuelle_app'@'localhost';

FLUSH PRIVILEGES;
