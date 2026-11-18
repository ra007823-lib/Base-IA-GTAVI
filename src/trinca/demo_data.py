"""Dados do modo de demonstração, todos fictícios.

Edite este arquivo para trocar os canais, vídeos e curiosidades de exemplo.
Nada aqui descreve canais, vídeos ou conteúdo reais.

Cada vídeo com "initial": True já aparece no radar ao abrir o app. Os demais
são "detectados" um por vez quando o radar verifica o canal.
"""

from __future__ import annotations


def _channel_id(tag: str) -> str:
    return "UC" + f"demo{tag}".ljust(22, "0")


DEMO_CHANNELS = [
    {"youtube_id": _channel_id("Alfa"), "name": "Canal Demo Alfa"},
    {"youtube_id": _channel_id("Beta"), "name": "Canal Demo Beta"},
    {"youtube_id": _channel_id("Gama"), "name": "Canal Demo Gama"},
]

DEMO_VIDEOS = [
    {
        "channel": _channel_id("Alfa"),
        "youtube_id": "demoVid0001",
        "title": "[Exemplo] Explorei o mapa inteiro: o que encontrei",
        "published_at": "2026-11-14T18:00:00",
        "initial": True,
        "curiosities": [
            {
                "start_s": 132, "end_s": 158,
                "title": "Pedestres fogem da chuva",
                "description": "Quando começa a chover na praia, os pedestres correm para "
                               "baixo dos quiosques e reclamam do tempo.",
                "scene_hint": "Praia durante a chuva, câmera nos pedestres perto dos quiosques.",
                "script": "Repara nisso: quando a chuva chega na praia, ninguém fica parado. "
                          "Os pedestres correm para os quiosques e ainda reclamam do tempo.",
            },
            {
                "start_s": 421, "end_s": 450,
                "title": "Marcas de pneu ficam na areia",
                "description": "As marcas deixadas pelo carro na areia continuam visíveis por "
                               "vários minutos e somem aos poucos com a maré.",
                "scene_hint": "Carro fazendo curvas na areia, depois câmera parada nas marcas.",
                "script": "As marcas de pneu na areia não somem na hora. Elas ficam ali por "
                          "minutos, até a maré apagar tudo aos poucos.",
            },
            {
                "start_s": 903, "end_s": 931,
                "title": "Rádio muda com o bairro",
                "description": "A programação do rádio do carro muda de acordo com o bairro "
                               "em que o jogador está dirigindo.",
                "scene_hint": "Dirigir entre dois bairros com o rádio ligado e a troca audível.",
                "script": "O rádio do carro acompanha o bairro. Cruzou a ponte, mudou a "
                          "programação, sem você tocar em nada.",
            },
            {
                "start_s": 1510, "end_s": 1542,
                "title": "Vitrine reflete o trânsito",
                "description": "As vitrines das lojas do centro refletem os carros que passam "
                               "na rua em tempo real.",
                "scene_hint": "Personagem parado em frente a uma vitrine, carros passando atrás.",
                "script": "Olha a vitrine: os carros que passam atrás de você aparecem "
                          "refletidos ali, na hora.",
            },
        ],
    },
    {
        "channel": _channel_id("Beta"),
        "youtube_id": "demoVid0002",
        "title": "[Exemplo] Primeiras 3 horas: gameplay comentada",
        "published_at": "2026-11-15T15:30:00",
        "initial": True,
        "curiosities": [
            {
                "start_s": 245, "end_s": 270,
                "title": "Celular com bateria",
                "description": "O celular do personagem perde bateria com o uso e pode ser "
                               "carregado dentro do carro.",
                "scene_hint": "Tela do celular com bateria baixa e depois o carregador no carro.",
                "script": "O celular do personagem descarrega de verdade. A saída é plugar no "
                          "carro e seguir viagem.",
            },
            {
                "start_s": 1980, "end_s": 2011,
                "title": "Lojas fecham à noite",
                "description": "Parte do comércio fecha as portas à noite e reabre de manhã, "
                               "com funcionários chegando para trabalhar.",
                "scene_hint": "Mesma rua de comércio à noite e de manhã, com as portas abrindo.",
                "script": "Nem toda loja fica aberta de madrugada. Volte de manhã e veja os "
                          "funcionários chegando para abrir as portas.",
            },
            {
                "start_s": 5400, "end_s": 5432,
                "title": "Roupa molhada demora a secar",
                "description": "Depois de sair do mar, a roupa do personagem fica escura e "
                               "seca aos poucos sob o sol.",
                "scene_hint": "Sair do mar e ficar parado no sol, com zoom na roupa secando.",
                "script": "Saiu do mar, a roupa fica encharcada. E ela seca aos poucos, "
                          "conforme você fica no sol.",
            },
        ],
    },
    {
        "channel": _channel_id("Gama"),
        "youtube_id": "demoVid0003",
        "title": "[Exemplo] Testei a polícia no limite",
        "published_at": "2026-11-16T09:10:00",
        "initial": True,
        "curiosities": [
            {
                "start_s": 310, "end_s": 344,
                "title": "Testemunhas descrevem o carro",
                "description": "A polícia procura pelo modelo e pela cor do carro informados "
                               "por testemunhas, e trocar de veículo despista a busca.",
                "scene_hint": "Fuga, troca de carro em um beco e viatura passando direto.",
                "script": "A polícia não sabe onde você está: ela procura o carro que as "
                          "testemunhas descreveram. Trocou de carro, mudou o jogo.",
            },
            {
                "start_s": 1205, "end_s": 1236,
                "title": "Bloqueios usam o trânsito",
                "description": "Os bloqueios policiais aproveitam engarrafamentos e ruas "
                               "estreitas em vez de aparecerem em pontos fixos.",
                "scene_hint": "Perseguição chegando a um bloqueio montado em rua estreita.",
                "script": "Os bloqueios não aparecem sempre no mesmo lugar. A polícia fecha "
                          "justamente a rua estreita onde você ia passar.",
            },
            {
                "start_s": 2890, "end_s": 2918,
                "title": "Helicóptero perde você em túneis",
                "description": "O helicóptero da polícia perde o contato visual quando o "
                               "jogador entra em túneis e garagens.",
                "scene_hint": "Entrar em um túnel com o helicóptero acima e o alerta sumindo.",
                "script": "Com o helicóptero em cima, procure um túnel. Sem contato visual, "
                          "a busca esfria em segundos.",
            },
        ],
    },
    {
        "channel": _channel_id("Alfa"),
        "youtube_id": "demoVid0004",
        "title": "[Exemplo] 10 detalhes escondidos na cidade",
        "published_at": "2026-11-16T12:00:00",
        "initial": False,
        "curiosities": [
            {
                "start_s": 95, "end_s": 120,
                "title": "Grafites mudam com o tempo",
                "description": "Alguns muros recebem grafites novos conforme os dias passam "
                               "dentro do jogo.",
                "scene_hint": "Mesmo muro filmado em dois dias diferentes do jogo.",
                "script": "Passe pelo mesmo muro dias depois: o grafite mudou. A cidade "
                          "continua sendo pintada enquanto você joga.",
            },
            {
                "start_s": 640, "end_s": 668,
                "title": "Pássaros seguem barcos de pesca",
                "description": "Bandos de pássaros acompanham os barcos de pesca que voltam "
                               "para o porto no fim da tarde.",
                "scene_hint": "Porto ao entardecer, barco chegando com pássaros em volta.",
                "script": "No fim da tarde, olhe para o porto. Os pássaros seguem os barcos "
                          "de pesca que estão voltando.",
            },
            {
                "start_s": 1422, "end_s": 1450,
                "title": "Semáforos falham na tempestade",
                "description": "Durante tempestades fortes, alguns semáforos piscam em "
                               "amarelo e o trânsito fica mais lento.",
                "scene_hint": "Cruzamento na tempestade com os semáforos piscando.",
                "script": "Na tempestade, os semáforos começam a piscar em amarelo, e o "
                          "trânsito inteiro anda com mais cuidado.",
            },
        ],
    },
    {
        "channel": _channel_id("Beta"),
        "youtube_id": "demoVid0005",
        "title": "[Exemplo] Os veículos mais rápidos",
        "published_at": "2026-11-16T13:45:00",
        "initial": False,
        "curiosities": [
            {
                "start_s": 180, "end_s": 205,
                "title": "Motor esquenta em corridas longas",
                "description": "Em corridas longas o indicador de temperatura sobe e o carro "
                               "perde desempenho até esfriar.",
                "scene_hint": "Painel do carro em primeira pessoa com a temperatura subindo.",
                "script": "Pisou fundo por muito tempo? O motor esquenta e o carro perde "
                          "força até esfriar.",
            },
            {
                "start_s": 760, "end_s": 792,
                "title": "Pneus gastos mudam a direção",
                "description": "Pneus muito gastos deixam o carro mais solto nas curvas, e "
                               "uma oficina resolve o problema.",
                "scene_hint": "Curva com o carro escorregando e depois a entrada na oficina.",
                "script": "Carro escorregando demais na curva pode ser pneu gasto. Uma "
                          "passada na oficina resolve.",
            },
            {
                "start_s": 1333, "end_s": 1360,
                "title": "Lancha deixa rastro visível do alto",
                "description": "O rastro das lanchas na água pode ser visto de prédios altos "
                               "por vários segundos.",
                "scene_hint": "Vista do alto de um prédio para a baía com uma lancha passando.",
                "script": "Do alto de um prédio dá para seguir o rastro que uma lancha "
                          "deixa na baía por vários segundos.",
            },
        ],
    },
]


for _video in DEMO_VIDEOS:
    _video["duration_s"] = int(max(item["end_s"] for item in _video["curiosities"])) + 180


def find_video(youtube_id: str) -> dict | None:
    for video in DEMO_VIDEOS:
        if video["youtube_id"] == youtube_id:
            return video
    return None


def script_line(video_youtube_id: str, start_s: float) -> str | None:
    """Texto de roteiro de exemplo para a curiosidade indicada."""
    video = find_video(video_youtube_id)
    if video is None:
        return None
    for item in video["curiosities"]:
        if item["start_s"] == start_s:
            return item["script"]
    return None
