// Behavioural stand-in for the MachXO2 EFB (SPI slave + WISHBONE), SIMULATION ONLY.
//
// RECOVERED vs MODELLED
// - Recovered from the bitstream: fabric port list, config (parameters, efb_decode.py).
// - Modelled (MachXO2 EFB register map, TN1205; NOT checked against silicon or the
//   vendor simulator, which is encrypted):
//     * WISHBONE classic slave, ACK one cycle after STB&CYC.
//     * SPI registers 0x54..0x5D (CR0..CR2, BR, CSR, TXDR, SR, RXDR, IRQ, IRQEN).
//     * Hardened SPI slave front end (mode 0, MSB first), driven by the testbench
//       through spi_xfer(); the pins are dedicated on silicon, so they are
//       model-internal here.
//     * Any other address: plain byte store.
// - Not modelled: I2C, timer/counter, UFM, PLL port, interrupts; JSPISCSN is ignored
//   (spi_csn_i is the chip select).
// SR bits: TIP 7, BUSY 6, TRDY 4, RRDY 3, TOE 2, ROE 1, MDF 0.
`timescale 1ns/1ps

module EFB #(
    parameter EFB_I2C1 = "DISABLED",
    parameter EFB_I2C2 = "DISABLED",
    parameter EFB_SPI = "DISABLED",
    parameter EFB_TC = "DISABLED",
    parameter SPI_MODE = "SLAVE",
    parameter SPI_CLK_DIVIDER = "1",
    parameter SPI_WAKEUP = "DISABLED",
    parameter SPI_LSB_FIRST = "DISABLED",
    parameter SPI_PHASE_ADJ = "DISABLED",
    parameter SPI_CLK_INV = "DISABLED",
    parameter SPI_SLAVE_HANDSHAKE = "DISABLED",
    parameter SPI_INTR_RXOVR = "DISABLED",
    parameter SPI_INTR_TXOVR = "DISABLED",
    parameter SPI_INTR_RXRDY = "DISABLED",
    parameter SPI_INTR_TXRDY = "DISABLED"
) (
    input  wire JWBCLKI,
    input  wire JWBRSTI,
    input  wire JWBCYCI,
    input  wire JWBSTBI,
    input  wire JWBWEI,
    input  wire JWBADRI0, JWBADRI1, JWBADRI2, JWBADRI3,
    input  wire JWBADRI4, JWBADRI5, JWBADRI6, JWBADRI7,
    input  wire JWBDATI0, JWBDATI1, JWBDATI2, JWBDATI3,
    input  wire JWBDATI4, JWBDATI5, JWBDATI6, JWBDATI7,
    output wire JWBACKO,
    output wire JWBDATO0, JWBDATO1, JWBDATO2, JWBDATO3,
    output wire JWBDATO4, JWBDATO5, JWBDATO6, JWBDATO7,
    input  wire JSPISCSN
);
    wire [7:0] adr  = {JWBADRI7, JWBADRI6, JWBADRI5, JWBADRI4,
                       JWBADRI3, JWBADRI2, JWBADRI1, JWBADRI0};
    wire [7:0] dati = {JWBDATI7, JWBDATI6, JWBDATI5, JWBDATI4,
                       JWBDATI3, JWBDATI2, JWBDATI1, JWBDATI0};

    localparam A_CR1 = 8'h55, A_CSR = 8'h58, A_TXDR = 8'h59, A_SR = 8'h5A,
               A_RXDR = 8'h5B;

    reg [7:0] regs [0:255];
    reg [7:0] dato = 8'h00;
    reg       ack  = 1'b0;

    reg [7:0] txdr = 8'h00, rxdr = 8'h00;
    reg       trdy = 1'b1, rrdy = 1'b0, toe = 1'b0, roe = 1'b0, tip = 1'b0;
    // testbench-driven SPI pins (dedicated on silicon)
    reg       spi_sck_i = 1'b0, spi_mosi_i = 1'b0, spi_csn_i = 1'b1;
    reg       spi_miso_o = 1'b0;

    reg trace;                                  // +efb_trace prints every WB cycle
    integer wb_reads = 0, wb_writes = 0, spi_bytes = 0;
    reg [255:0] adr_seen = 256'b0;              // addresses touched by the fabric

    integer i;
    initial begin
        trace = $test$plusargs("efb_trace");
        for (i = 0; i < 256; i = i + 1) regs[i] = 8'h00;
        regs[A_CR1] = 8'h80;                    // SPE, from the recovered config payload
        regs[A_CSR] = 8'hFF;
    end

    wire [7:0] sr = {tip, tip, 1'b0, trdy, rrdy, toe, roe, 1'b0};

    function [7:0] rd(input [7:0] a);
        case (a)
            A_SR:    rd = sr;
            A_RXDR:  rd = rxdr;
            A_TXDR:  rd = txdr;
            default: rd = regs[a];
        endcase
    endfunction

    always @(posedge JWBCLKI) begin
        if (JWBRSTI === 1'b1) begin
            ack  <= 1'b0;
            dato <= 8'h00;
        end else if ((JWBSTBI === 1'b1) && (JWBCYCI === 1'b1) && !ack) begin
            adr_seen[adr] = 1'b1;
            if (JWBWEI === 1'b1) begin
                wb_writes = wb_writes + 1;
                case (adr)
                    A_TXDR:       begin txdr <= dati; trdy <= 1'b0; end
                    A_SR, A_RXDR: ;
                    default:      regs[adr] <= dati;
                endcase
                if (trace) $display("WB t=%0t WR a=%h d=%h", $time, adr, dati);
            end else begin
                wb_reads = wb_reads + 1;
                dato <= rd(adr);
                if (adr == A_RXDR) rrdy <= 1'b0;
                if (adr == A_SR)   begin toe <= 1'b0; roe <= 1'b0; end
                if (trace) $display("WB t=%0t RD a=%h d=%h", $time, adr, rd(adr));
            end
            ack <= 1'b1;
        end else begin
            ack <= 1'b0;
        end
    end

    assign {JWBDATO7, JWBDATO6, JWBDATO5, JWBDATO4,
            JWBDATO3, JWBDATO2, JWBDATO1, JWBDATO0} = dato;
    assign JWBACKO = ack;

    // One SPI byte, mode 0, MSB first, driven by the testbench.
    // TX: TXDR if loaded (TRDY=0) else 0x00 (+TOE).  RX: RXDR <= byte, RRDY=1 (+ROE if
    // the previous byte was never read).
    task spi_xfer(input [7:0] mosi, output [7:0] miso, input integer sck_half_ns);
        integer b;
        reg [7:0] tx, rx;
        begin
            tx = trdy ? 8'h00 : txdr;
            rx = 8'h00;
            spi_csn_i = 1'b0;
            tip = 1'b1;
            for (b = 7; b >= 0; b = b - 1) begin
                spi_mosi_i = mosi[b];
                spi_miso_o = tx[b];
                #(sck_half_ns) spi_sck_i = 1'b1;
                rx[b] = spi_mosi_i;
                #(sck_half_ns) spi_sck_i = 1'b0;
            end
            tip = 1'b0;
            miso = tx;
            if (rrdy) roe = 1'b1;
            rxdr = rx;
            rrdy = 1'b1;
            if (trdy) toe = 1'b1; else trdy = 1'b1;
            spi_bytes = spi_bytes + 1;
        end
    endtask
    task spi_cs(input level);
        begin spi_csn_i = level; end
    endtask

    task wb_poke(input [7:0] a, input [7:0] d);
        begin regs[a] = d; end
    endtask
    function [7:0] wb_peek(input [7:0] a);
        begin wb_peek = rd(a); end
    endfunction
endmodule
