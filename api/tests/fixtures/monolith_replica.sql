CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION immutable_unaccent(text) RETURNS text AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;

CREATE ROLE cerebro_reader LOGIN PASSWORD 'local-read-only';

CREATE TABLE "user" (id uuid PRIMARY KEY, "createdAt" timestamp NOT NULL, "updatedAt" timestamp NOT NULL);
CREATE TABLE personal_details (id uuid PRIMARY KEY, "userId" uuid NOT NULL, "firstName" varchar NOT NULL, "lastName" varchar NOT NULL, rut varchar);
CREATE TABLE contact_info (id uuid PRIMARY KEY, "userId" uuid NOT NULL, email varchar NOT NULL, phone varchar NOT NULL);
CREATE TABLE house (id uuid PRIMARY KEY, "communeId" uuid NOT NULL, "addressStreet" varchar NOT NULL, "addressExternalNumber" varchar, "addressInternalNumber" varchar);
CREATE TABLE commune (id uuid PRIMARY KEY, name varchar NOT NULL);
CREATE TABLE "order" (id uuid PRIMARY KEY, "orderNumber" integer NOT NULL, "houseId" uuid NOT NULL, "userId" uuid NOT NULL);
CREATE TABLE quote (id uuid PRIMARY KEY, "houseId" uuid NOT NULL, price integer NOT NULL, "acceptedAt" timestamp);
CREATE TABLE booking (id uuid PRIMARY KEY, "userId" uuid NOT NULL, "orderId" uuid NOT NULL, "quoteId" uuid NOT NULL, "confirmedAt" timestamp, "createdAt" timestamp NOT NULL);
CREATE TABLE sale (id uuid PRIMARY KEY, "bookingId" uuid NOT NULL, "createdAt" timestamp NOT NULL);
CREATE TABLE solar_system_installation (id uuid PRIMARY KEY, "saleId" uuid NOT NULL, "canceledAt" timestamp, "completedAt" timestamp);
CREATE TABLE account_receivable (id uuid PRIMARY KEY, "saleId" uuid NOT NULL, amount numeric NOT NULL, currency varchar NOT NULL, debtor varchar NOT NULL, recipient varchar NOT NULL, type varchar NOT NULL, "canceledAt" timestamp);
CREATE TABLE account_receivable_payment (id uuid PRIMARY KEY, "accountReceivableId" uuid NOT NULL, amount numeric NOT NULL, currency varchar NOT NULL, "deletedAt" timestamp, "paymentDate" timestamp, comments text);
CREATE TABLE account_receivable_loss (id uuid PRIMARY KEY, "accountReceivableId" uuid NOT NULL, amount numeric NOT NULL, currency varchar NOT NULL, "deletedAt" timestamp, comments text);
CREATE TABLE account_receivable_installment_type (id varchar PRIMARY KEY, name varchar NOT NULL);
CREATE TABLE account_receivable_installment (id uuid PRIMARY KEY, "accountReceivableId" uuid NOT NULL, "typeId" varchar NOT NULL, percentage numeric NOT NULL, "disbursementDate" timestamp, "createdAt" timestamp NOT NULL);
CREATE TABLE vambe_message (id uuid PRIMARY KEY, "createdAt" timestamp NOT NULL, direction text NOT NULL, type text NOT NULL, content text, "phoneNumber" text NOT NULL, "channelPhoneNumber" text, "userId" uuid, status text, "stageId" uuid, "senderId" varchar);
CREATE TABLE bank_account (id uuid PRIMARY KEY, "solarSystemInstallationId" uuid, bank text NOT NULL, "accountNumber" varchar NOT NULL, "accountType" text NOT NULL, "fullName" varchar, rut varchar, phone varchar, email varchar);
CREATE TABLE chile_bank_account (id uuid PRIMARY KEY, "fullName" varchar NOT NULL, "accountNumber" varchar NOT NULL, "accountType" text NOT NULL, rut varchar NOT NULL, email varchar, bank text NOT NULL);
CREATE TABLE certification_user (id uuid PRIMARY KEY, "bookingId" uuid NOT NULL, "chileBankAccountId" uuid, "firstName" varchar NOT NULL, "lastName" varchar NOT NULL, rut varchar NOT NULL, phone varchar NOT NULL, email varchar NOT NULL);

INSERT INTO "user" VALUES ('00000000-0000-0000-0000-000000000001', now(), now());
INSERT INTO personal_details VALUES ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'María', 'Solar', '11.111.111-1');
INSERT INTO contact_info VALUES ('20000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'maria@example.test', '+56911111111');
INSERT INTO commune VALUES ('30000000-0000-0000-0000-000000000001', 'Las Condes');
INSERT INTO house VALUES ('40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'Los Paneles', '123', NULL);
INSERT INTO "order" VALUES ('50000000-0000-0000-0000-000000000001', 4242, '40000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001');
INSERT INTO quote VALUES ('60000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', 1000000, now());
INSERT INTO booking VALUES ('70000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001', '60000000-0000-0000-0000-000000000001', now(), now());
INSERT INTO sale VALUES ('80000000-0000-0000-0000-000000000001', '70000000-0000-0000-0000-000000000001', now());
INSERT INTO solar_system_installation VALUES ('90000000-0000-0000-0000-000000000001', '80000000-0000-0000-0000-000000000001', NULL, NULL);
INSERT INTO account_receivable VALUES ('a0000000-0000-0000-0000-000000000001', '80000000-0000-0000-0000-000000000001', 1000000, 'CLP', 'client', 'ruuf', 'cash', NULL);
INSERT INTO account_receivable_payment VALUES ('b0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 300000, 'CLP', NULL, now(), 'synthetic fixture');
INSERT INTO account_receivable_loss VALUES ('c0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 0, 'CLP', NULL, 'synthetic fixture');
INSERT INTO account_receivable_installment_type VALUES ('pre-installation', 'Antes de instalación'), ('post-installation', 'Después de instalación');
INSERT INTO account_receivable_installment VALUES ('d0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'pre-installation', 0.7, now(), now());
INSERT INTO bank_account VALUES ('e0000000-0000-0000-0000-000000000001', '90000000-0000-0000-0000-000000000001', 'Banco BICE', '12345678', 'corriente', 'María Solar', '11.111.111-1', '+56911111111', 'maria@example.test');
INSERT INTO chile_bank_account VALUES ('f0000000-0000-0000-0000-000000000001', 'María Solar', '87654321', 'corriente', '11.111.111-1', 'maria@example.test', 'Banco BICE');
INSERT INTO certification_user VALUES ('11000000-0000-0000-0000-000000000001', '70000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000001', 'María', 'Solar', '11.111.111-1', '+56911111111', 'maria@example.test');
INSERT INTO vambe_message VALUES ('12000000-0000-0000-0000-000000000001', now(), 'inbound', 'text', 'Envié el comprobante del pago de 700000', '+56911111111', NULL, '00000000-0000-0000-0000-000000000001', 'sent', NULL, NULL);

GRANT USAGE ON SCHEMA public TO cerebro_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cerebro_reader;
ALTER ROLE cerebro_reader SET default_transaction_read_only = on;
ALTER ROLE cerebro_reader SET statement_timeout = '15s';
