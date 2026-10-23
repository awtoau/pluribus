module c_fsm_oh_sv_8 (input logic clk, rst, go, alt, output logic done, odd);
  typedef enum logic [7:0] {S0 = 8'b00000001, S1 = 8'b00000010, S2 = 8'b00000100, S3 = 8'b00001000, S4 = 8'b00010000, S5 = 8'b00100000, S6 = 8'b01000000, S7 = 8'b10000000} state_t;
  state_t st, nx;
  always_comb begin
    nx = S0;
    case (st)
      S0: begin
        if (go) nx = S1;
        else nx = S0;
      end
      S1: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S2;
        else nx = S1;
      end
      S2: begin
        if (go) nx = S3;
        else nx = S2;
      end
      S3: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S4;
        else nx = S3;
      end
      S4: begin
        if (go) nx = S5;
        else nx = S4;
      end
      S5: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S6;
        else nx = S5;
      end
      S6: begin
        if (go) nx = S7;
        else nx = S6;
      end
      S7: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S0;
        else nx = S7;
      end
      default: nx = S0;
    endcase
  end
  always_ff @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S7);
  assign odd = (st == S1) | (st == S3) | (st == S5) | (st == S7);
endmodule
