// An IP-FREE stand-in for the MachXO2 EFB, for SIMULATION ONLY.
//
// WHY
// ---
// The recovered netlist instantiates `EFB` as a (* blackbox *): correct, because
// the EFB is hard IP whose internals are not in the bitstream.  A blackbox
// drives nothing, so every fabric net the EFB feeds sits at X and the recovered
// scope datapath never does anything.  This module replaces it with open logic
// so the fabric can be exercised.
//
// WHAT IT MODELS, AND WHAT IT DOES NOT
// ------------------------------------
// The recovered interface is a WISHBONE slave -- 8-bit address, 8-bit data each
// way, CLK/STB/CYC/WE/ACK -- all 30 ports recovered from the bitstream.  This
// models exactly that bus, and NOTHING else: no I2C, no timer/counter, no UFM,
// no PLL config port, no sysCONFIG behaviour.  Those are absent from this design
// or irrelevant to the datapath.
//
// It is NOT a model of the hardened SPI slave.  On MachXO2 the SPI clock and
// data are on dedicated sysCONFIG pins wired to the EFB in silicon; they never
// enter the fabric, so nothing about them appears in the bitstream and there is
// nothing to recover.  Only JSPISCSN (chip-select) is fabric-routed and shows up.
// Rather than invent a serial front end, the testbench drives the WISHBONE side
// directly -- same register writes, none of the guesswork.  See
// scripts/efb_wb_boot.vh.
//
// FIDELITY
// --------
// Register STORAGE is faithful (a write lands, a read returns it, ACK is one
// cycle).  Register SEMANTICS are not modelled at all: writing ARM_CAPTURE here
// stores 0x07, it does not make hard IP start a capture.  Any behaviour observed
// downstream therefore comes from the RECOVERED FABRIC responding to the bus,
// which is the whole point of the exercise.
//
// The port list mirrors the recovered instantiation exactly; unused inputs are
// accepted and ignored so the module is a drop-in.
`timescale 1ns/1ps

module EFB (
    // WISHBONE slave -- the recovered interface
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
    // present in the recovered netlist, accepted and unused here
    input  wire JSPISCSN,
    input  wire JWBCUFMIRQ,
    output wire JSPIIRQO,
    output wire JI2C1IRQO,
    output wire JI2C2IRQO,
    output wire JTCINT,
    output wire JTCOC
);
    wire [7:0] adr = {JWBADRI7, JWBADRI6, JWBADRI5, JWBADRI4,
                      JWBADRI3, JWBADRI2, JWBADRI1, JWBADRI0};
    wire [7:0] dati = {JWBDATI7, JWBDATI6, JWBDATI5, JWBDATI4,
                       JWBDATI3, JWBDATI2, JWBDATI1, JWBDATI0};

    // 256 x 8 register file.  The board's map (boards/<board>/spi_registers.tsv)
    // uses addresses well under 0x100, so a flat file covers every bank.
    reg [7:0] regs [0:255];
    reg [7:0] dato = 8'h00;
    reg       ack  = 1'b0;

    integer i;
    initial begin
        for (i = 0; i < 256; i = i + 1) regs[i] = 8'h00;
    end

    // Single-cycle WISHBONE classic: ACK follows an accepted STB+CYC.
    always @(posedge JWBCLKI) begin
        if (JWBRSTI === 1'b1) begin
            ack  <= 1'b0;
            dato <= 8'h00;
        end else if ((JWBSTBI === 1'b1) && (JWBCYCI === 1'b1) && !ack) begin
            if (JWBWEI === 1'b1) regs[adr] <= dati;
            else                 dato      <= regs[adr];
            ack <= 1'b1;
        end else begin
            ack <= 1'b0;
        end
    end

    assign {JWBDATO7, JWBDATO6, JWBDATO5, JWBDATO4,
            JWBDATO3, JWBDATO2, JWBDATO1, JWBDATO0} = dato;
    assign JWBACKO = ack;

    // Peripherals this design does not use: held inactive rather than left X,
    // so they cannot poison the fabric through an unmodelled path.
    assign JSPIIRQO  = 1'b0;
    assign JI2C1IRQO = 1'b0;
    assign JI2C2IRQO = 1'b0;
    assign JTCINT    = 1'b0;
    assign JTCOC     = 1'b0;

    // Let the testbench poke registers directly, standing in for the MCU's SPI
    // writes without modelling a serial front end that is not in the bitstream.
    task wb_poke(input [7:0] a, input [7:0] d);
        begin regs[a] = d; end
    endtask
    function [7:0] wb_peek(input [7:0] a);
        begin wb_peek = regs[a]; end
    endfunction
endmodule
