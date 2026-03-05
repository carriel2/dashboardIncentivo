--
-- PostgreSQL database dump
--

\restrict iXar43gre5H0l4UOVMbE4h68u6ynoBTIvxlCbwEXWbVIKOV4OpAJi7TuAma1hKg

-- Dumped from database version 15.17
-- Dumped by pg_dump version 15.17

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: client_conversions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.client_conversions (
    uid integer NOT NULL,
    email character varying(255),
    conversion_date timestamp without time zone
);


ALTER TABLE public.client_conversions OWNER TO postgres;

--
-- Name: daily_billing; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.daily_billing (
    id integer NOT NULL,
    date timestamp without time zone,
    uid integer,
    email character varying(255),
    consumption numeric(10,4)
);


ALTER TABLE public.daily_billing OWNER TO postgres;

--
-- Name: daily_billing_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.daily_billing_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.daily_billing_id_seq OWNER TO postgres;

--
-- Name: daily_billing_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.daily_billing_id_seq OWNED BY public.daily_billing.id;


--
-- Name: daily_billing id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_billing ALTER COLUMN id SET DEFAULT nextval('public.daily_billing_id_seq'::regclass);


--
-- Data for Name: client_conversions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.client_conversions (uid, email, conversion_date) FROM stdin;
\.


--
-- Data for Name: daily_billing; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.daily_billing (id, date, uid, email, consumption) FROM stdin;
20	2026-03-02 00:00:00	37014	agenciai3focus@gmail.com	10.3706
21	2026-03-02 00:00:00	37020	cloud@efxpix.com.br	6.2865
22	2026-03-02 00:00:00	37236	contato@cahuonlinesystems.online	7.2012
23	2026-03-02 00:00:00	20867	contato@multsistem.com.br	33.3356
24	2026-03-02 00:00:00	37192	dev@cognitus-erp.com.br	7.6255
25	2026-03-02 00:00:00	37172	eugenio@eugon.com.br	6.4653
26	2026-03-02 00:00:00	37031	gustavo@omsistemas.com	0.0000
27	2026-03-02 00:00:00	26065	helio@sistemaquantum.com.br	65.3076
28	2026-03-02 00:00:00	37065	igorsamuel.souza2@gmail.com	0.0316
29	2026-03-02 00:00:00	37199	infra@gestorrevenda.com.br	5.7652
30	2026-03-02 00:00:00	37388	julio.santaratto@hinosistemas.com.br	12.9622
31	2026-03-02 00:00:00	37272	liwston@gmail.com	0.0000
32	2026-03-02 00:00:00	37426	ljbruno702@gmail.com	0.5753
33	2026-03-02 00:00:00	37507	mariellenzg@gmail.com	7.9980
34	2026-03-02 00:00:00	37421	mateus@jusmatic.ia.br	20.3424
35	2026-03-02 00:00:00	37494	pedro@mystra.com.br	0.0000
36	2026-03-02 00:00:00	34181	renato.neves@baseele.com.br	0.7608
37	2026-03-02 00:00:00	37530	ronaldo@oessistemas.com.br	0.0000
38	2026-03-02 00:00:00	37189	silas@adalagoas.org.br	2.1492
39	2026-03-03 00:00:00	37014	agenciai3focus@gmail.com	10.3722
40	2026-03-03 00:00:00	37020	cloud@efxpix.com.br	6.2097
41	2026-03-03 00:00:00	37236	contato@cahuonlinesystems.online	7.2014
42	2026-03-03 00:00:00	20867	contato@multsistem.com.br	33.3391
43	2026-03-03 00:00:00	37192	dev@cognitus-erp.com.br	7.6255
44	2026-03-03 00:00:00	37172	eugenio@eugon.com.br	6.5980
45	2026-03-03 00:00:00	37031	gustavo@omsistemas.com	0.0000
46	2026-03-03 00:00:00	26065	helio@sistemaquantum.com.br	75.3847
47	2026-03-03 00:00:00	37065	igorsamuel.souza2@gmail.com	0.0316
48	2026-03-03 00:00:00	37199	infra@gestorrevenda.com.br	5.4468
49	2026-03-03 00:00:00	37388	julio.santaratto@hinosistemas.com.br	12.9628
50	2026-03-03 00:00:00	37272	liwston@gmail.com	0.0000
51	2026-03-03 00:00:00	37426	ljbruno702@gmail.com	0.5753
52	2026-03-03 00:00:00	37507	mariellenzg@gmail.com	7.9980
53	2026-03-03 00:00:00	37421	mateus@jusmatic.ia.br	22.1330
54	2026-03-03 00:00:00	37494	pedro@mystra.com.br	0.0000
55	2026-03-03 00:00:00	34181	renato.neves@baseele.com.br	3.4175
56	2026-03-03 00:00:00	37530	ronaldo@oessistemas.com.br	0.0000
57	2026-03-03 00:00:00	37189	silas@adalagoas.org.br	2.1492
\.


--
-- Name: daily_billing_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.daily_billing_id_seq', 57, true);


--
-- Name: client_conversions client_conversions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.client_conversions
    ADD CONSTRAINT client_conversions_pkey PRIMARY KEY (uid);


--
-- Name: daily_billing daily_billing_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_billing
    ADD CONSTRAINT daily_billing_pkey PRIMARY KEY (id);


--
-- PostgreSQL database dump complete
--

\unrestrict iXar43gre5H0l4UOVMbE4h68u6ynoBTIvxlCbwEXWbVIKOV4OpAJi7TuAma1hKg

