import uuid
from sqlalchemy import (
    Column,
    Numeric,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Text,
    Integer,
    Date
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(120), nullable=False)
    whatsapp_phone_number_id = Column(String(64), unique=True, nullable=False)
    timezone = Column(String(32), nullable=False, default="America/Fortaleza")
    config_json = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    kits = relationship("KitFesta", back_populates="tenant")
    clientes = relationship("Cliente", back_populates="tenant")
    conversas = relationship("Conversation", back_populates="tenant")
    mensagens = relationship("MensagemWhatsapp", back_populates="tenant")
    usuarios_admin = relationship("UsuarioAdmin", back_populates="tenant")
    registros_alugueis = relationship("RegistroAluguel", back_populates="tenant")


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    message_id = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", name="uq_processed_tenant_msg"),
    )


class FAQ(Base):
    __tablename__ = "faq"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KitFesta(Base):
    __tablename__ = "kits_festa"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    nome_kit = Column(String, nullable=False)
    categoria = Column(String, nullable=True)
    tema = Column(String, nullable=True)
    codigo_kit = Column(String, nullable=False, unique=True)

    valor_locacao = Column(String, nullable=True)
    status_disponibilidade = Column(String, nullable=True)
    quantidade_itens = Column(String, nullable=True)
    descricao = Column(Text, nullable=True)
    observacoes = Column(Text, nullable=True)
    ativo = Column(Boolean, default=True)

    tenant = relationship("Tenant", back_populates="kits")
    fotos = relationship("KitFoto", back_populates="kit", cascade="all, delete-orphan")
    registros_alugueis = relationship("RegistroAluguel", back_populates="kit")


class KitFoto(Base):
    __tablename__ = "kit_fotos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kit_id = Column(UUID(as_uuid=True), ForeignKey("kits_festa.id", ondelete="CASCADE"), nullable=False)
    foto_url = Column(String, nullable=False)
    ordem = Column(Integer, default=0)

    kit = relationship("KitFesta", back_populates="fotos")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_wa_id = Column(String(32), nullable=False)
    state = Column(Text, nullable=True)    
    contexto_json = Column(JSONB, nullable=False, default=dict)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    atendimento_humano = Column(Boolean, default=False)
    status_atendimento = Column(String, nullable=True)
    assunto = Column(String, nullable=True)

    tenant = relationship("Tenant", back_populates="conversas")


class MensagemWhatsapp(Base):
    __tablename__ = "mensagens_whatsapp"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    telefone_usuario = Column(String(30), nullable=False)
    tipo_mensagem = Column(String(20), nullable=False)
    conteudo = Column(Text, nullable=True)
    mensagem_id_whatsapp = Column(String(120), nullable=True)

    tipo_conteudo = Column(String(30), nullable=False, default="texto")
    media_url = Column(Text, nullable=True)
    media_mime_type = Column(String(255), nullable=True)
    media_filename = Column(String(255), nullable=True)
    media_id = Column(String(255), nullable=True)

    criada_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="mensagens")


class UsuarioAdmin(Base):
    __tablename__ = "usuarios_admin"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    nome = Column(String(120), nullable=False)
    email = Column(String(120), nullable=False, unique=True)
    senha_hash = Column(String(255), nullable=False)

    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="usuarios_admin")


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    nome = Column(String, nullable=False)
    telefone = Column(String, nullable=False, index=True)
    endereco = Column(String, nullable=True)
    cpf = Column(String, nullable=True, index=True)

    saldo = Column(Numeric(10, 2), nullable=False, default=0)
    quantidade_alugueis = Column(Integer, nullable=False, default=0)
    aluguel_em_curso = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="clientes")
    registros_alugueis = relationship("RegistroAluguel", back_populates="cliente")


class RegistroAluguel(Base):
    __tablename__ = "registros_alugueis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False, index=True)
    kit_id = Column(UUID(as_uuid=True), ForeignKey("kits_festa.id"), nullable=False, index=True)

    # período planejado da reserva
    data_reserva = Column(Date, nullable=False, index=True)
    data_entrega = Column(Date, nullable=False, index=True)

    valor_cobrado = Column(Numeric(10, 2), nullable=True)
    valor_pago = Column(Numeric(10, 2), nullable=True)
    pagamento_status = Column(String(50), nullable=True)
    pagamento_metodo = Column(String(50), nullable=True)

    status = Column(String(50), nullable=False, default="reservado")
    observacoes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="registros_alugueis")
    cliente = relationship("Cliente", back_populates="registros_alugueis")
    kit = relationship("KitFesta", back_populates="registros_alugueis")

# aliases de compatibilidade para reaproveitar partes do sistema antigo
Aluno = KitFesta
Contact = Cliente