-- Расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Cloud users (для будущей облачной авторизации и подписок)
CREATE TABLE IF NOT EXISTS cloud_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hwid VARCHAR(255) UNIQUE,
    subscription_tier VARCHAR(50) DEFAULT 'free',
    subscription_expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Marketplace items (заглушка)
CREATE TABLE IF NOT EXISTS marketplace_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(50),
    stock INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
